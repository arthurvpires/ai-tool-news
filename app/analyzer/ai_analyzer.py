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
    "llama-3.3-70b-versatile",
]


MIN_RELEVANT_SCORE = 5


class AIAnalysisResult(BaseModel):
    relevance_score: int = Field(description="A score from 1 to 10 on the importance of the update.")
    reason: str = Field(description="A short explanation of why it is relevant or not.")
    category: str = Field(description="The category of the update.")


class AIComparisonResult(BaseModel):
    is_duplicate: bool = Field(description="Whether the new post is a duplicate of the existing one.")
    confidence: float = Field(description="Confidence score from 0 to 1.0.")
    event_summary: str = Field(default="", description="One short sentence describing the event.")
    reason: str = Field(description="Short explanation of why it is or is not a duplicate.")


class AIAnalyzer:
    def __init__(self):
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts.yaml")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                prompts = yaml.safe_load(f)
                self.system_prompt = prompts.get("ai_scout", {}).get("system_prompt", "")
                self.dedup_prompt = prompts.get("deduplicator", {}).get("system_prompt", "")
        except Exception as e:
            logger.error(f"Failed to load prompts.yaml: {e}")
            self.system_prompt = "You are an AI news filter."
            self.dedup_prompt = "You are an AI duplicate detector."

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

    def find_duplicate(self, content: str, existing_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not content or not existing_items:
            return {"is_duplicate": False, "confidence": 0, "reason": "No content or existing items to compare."}

        if not self.openai_client and not self.groq_client:
            return {"is_duplicate": False, "confidence": 0, "reason": "No LLM client available for deduplication."}

        try:
            # We compare with the top 5 most recent/relevant items to save tokens
            logger.info(f"Checking for duplicates among {len(existing_items[:5])} recent items...")
            for item in existing_items[:5]:
                existing_text = item.get("text", "")
                if not existing_text:
                    continue

                if self.openai_client:
                    response = self.openai_client.beta.chat.completions.parse(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": self.dedup_prompt},
                            {
                                "role": "user",
                                "content": f"New Post:\n{content}\n\nExisting Post:\n{existing_text}",
                            },
                        ],
                        response_format=AIComparisonResult,
                        max_tokens=200,
                    )
                    result = response.choices[0].message.parsed
                    is_duplicate = result.is_duplicate
                    confidence = result.confidence
                    reason = result.reason
                    event_summary = result.event_summary
                elif self.groq_client:
                    # Fallback to Groq
                    model = GROQ_MODELS[1] if len(GROQ_MODELS) > 1 else GROQ_MODELS[0]
                    response = self.groq_client.chat.completions.create(
                        model=model,
                        messages=[
                            {
                                "role": "system",
                                "content": self.dedup_prompt
                                + "\n\nReturn EXACTLY a valid JSON object with the keys: 'is_duplicate' (bool), 'confidence' (float), 'event_summary' (string), and 'reason' (string).",
                            },
                            {
                                "role": "user",
                                "content": f"New Post:\n{content}\n\nExisting Post:\n{existing_text}",
                            },
                        ],
                        response_format={"type": "json_object"},
                        max_tokens=200,
                    )
                    result_json = json.loads(response.choices[0].message.content)
                    is_duplicate = bool(result_json.get("is_duplicate", False))
                    confidence = float(result_json.get("confidence", 0.0))
                    reason = str(result_json.get("reason", ""))
                    event_summary = str(result_json.get("event_summary", ""))
                else:
                    continue

                if is_duplicate:
                    logger.info(f"  - Dup Found? {is_duplicate} | Conf: {confidence:.2f} | Event: {event_summary} | Reason: {reason}")
                else:
                    logger.debug(f"  - Not a duplicate of {item.get('content_id')} (Conf: {confidence:.2f})")

                if is_duplicate and confidence > 0.7:
                    return {
                        "is_duplicate": True,
                        "confidence": confidence,
                        "reason": reason,
                        "duplicate_id": item.get("content_id"),
                    }
            
            return {"is_duplicate": False, "confidence": 0, "reason": "No duplicates found among recent items."}
        except Exception as e:
            logger.error(f"Deduplication check failed: {e}")
            return {"is_duplicate": False, "confidence": 0, "reason": f"Error: {e}"}

    def _mock_analyze(self, text: str) -> Dict[str, Any]:
        text_lower = text.lower()
        is_relevant = any(keyword in text_lower for keyword in ["release", "launch", "new", "update", "model"])

        return {
            "relevant": is_relevant,
            "summary": "Mocked summary: This seems to be an important update."
            if is_relevant
            else "Mocked summary: Not important.",
        }
