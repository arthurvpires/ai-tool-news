from typing import Dict, Any, List
import logging
from openai import OpenAI
from pydantic import BaseModel, Field
from app.config import settings
import json

import yaml
import os

logger = logging.getLogger(__name__)

GROQ_MODELS = [
    "llama-3.1-8b-instant",
    "gemma2-9b-it",
]


MIN_RELEVANT_SCORE = 5


class AIAnalysisResult(BaseModel):
    relevance_score: int = Field(description="A score from 1 to 10 on the importance of the update.")
    reason: str = Field(description="A short explanation of why it is relevant or not.")
    category: str = Field(description="The category of the update.")


class AIAnalyzer:
    def __init__(self):
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts.yaml")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                prompts = yaml.safe_load(f)
                self.system_prompt = prompts.get("ai_scout", {}).get("system_prompt", "")
        except Exception as e:
            logger.error(f"Failed to load prompts.yaml: {e}")
            self.system_prompt = "You are an AI news filter."

        self.openai_client = None
        self.groq_client = None

        has_openai = settings.OPENAI_API_KEY and settings.OPENAI_API_KEY != "your_openai_api_key"
        has_groq = settings.GROQ_API_KEY and settings.GROQ_API_KEY != "your_groq_api_key"

        if has_openai:
            self.openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

        if has_groq:
            from groq import Groq
            self.groq_client = Groq(api_key=settings.GROQ_API_KEY)

        if not has_openai and not has_groq:
            logger.warning("No OPENAI_API_KEY or GROQ_API_KEY found. Analyzer will fall back to mocked logic.")

    def analyze(self, content: Dict[str, Any]) -> Dict[str, Any]:
        text = content.get("text", "")
        content_id = content.get("id", "unknown")

        if not text:
            return {"relevant": False, "summary": "No text content", "relevance_score": 0}

        if self.openai_client:
            try:
                return self._call_openai(text, content_id)
            except Exception as e:
                logger.warning(f"OpenAI failed for {content_id}: {e}")
                if not self.groq_client:
                    return {"relevant": False, "summary": "Analysis failed", "relevance_score": 0}
                logger.warning(f"Falling back to Groq...")

        if self.groq_client:
            return self._call_groq_with_fallback(text, content_id)

        return self._mock_analyze(text)

    def _call_openai(self, text, content_id):
        response = self.openai_client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"Please analyze the following content:\n\n{text}"},
            ],
            response_format=AIAnalysisResult,
            max_tokens=300,
        )
        result = response.choices[0].message.parsed
        relevant = result.relevance_score >= MIN_RELEVANT_SCORE
        mark = ">>>" if relevant else "   "
        logger.info(f"{mark} [{result.relevance_score:>2}/10] {content_id} | {result.reason}")
        return {
            "relevant": relevant,
            "relevance_score": result.relevance_score,
            "summary": result.reason,
            "category": result.category,
        }

    def _call_groq_with_fallback(self, text, content_id):
        for i, model in enumerate(GROQ_MODELS):
            try:
                return self._call_groq(model, text, content_id)
            except Exception as e:
                is_last = i == len(GROQ_MODELS) - 1
                if is_last:
                    logger.error(f"All Groq models failed for {content_id}: {e}")
                    return {"relevant": False, "summary": "Analysis failed", "relevance_score": 0}
                logger.warning(f"Groq {model} failed, trying next model...")

    def _call_groq(self, model, text, content_id):
        response = self.groq_client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": self.system_prompt
                    + "\n\nReturn EXACTLY a valid JSON object with the keys: 'relevance_score' (int), 'reason' (string), and 'category' (string).",
                },
                {"role": "user", "content": f"Please analyze the following content:\n\n{text}"},
            ],
            response_format={"type": "json_object"},
            max_tokens=300,
        )
        result_json = json.loads(response.choices[0].message.content)
        score = int(result_json.get("relevance_score", 0))
        relevant = score >= MIN_RELEVANT_SCORE
        reason = str(result_json.get("reason", result_json.get("summary", "")))

        mark = ">>>" if relevant else "   "
        logger.info(f"{mark} [{score:>2}/10] {content_id} | {reason}")
        return {
            "relevant": relevant,
            "relevance_score": score,
            "summary": reason,
            "category": result_json.get("category", "other"),
        }

    def _mock_analyze(self, text: str) -> Dict[str, Any]:
        text_lower = text.lower()
        is_relevant = any(keyword in text_lower for keyword in ["release", "launch", "new", "update", "model"])

        return {
            "relevant": is_relevant,
            "summary": "Mocked summary: This seems to be an important update."
            if is_relevant
            else "Mocked summary: Not important.",
        }
