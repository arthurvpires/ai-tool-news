from typing import Dict, Any, List, Optional
import logging
import yaml
import os
from pydantic import BaseModel, Field
from app.analyzer.ai_client import AIClient

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


class AIAnalyzer:
    def __init__(self):
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts.yaml")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                prompts = yaml.safe_load(f)
                self.system_prompt = prompts.get("ai_scout", {}).get("system_prompt", "")
                self.daily_prompt = prompts.get("daily_summary", {}).get("system_prompt", "")
        except Exception as e:
            logger.error(f"Failed to load prompts.yaml: {e}")
            self.system_prompt = "You are an AI news filter."
            self.daily_prompt = "Summarize the following AI news."

        self.ai_client = AIClient()

    def analyze(self, content: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        text = content.get("text", "")
        content_id = content.get("id", "unknown")

        if not text:
            return {"relevant": False, "summary": "No text content", "relevance_score": 0}

        from app.analyzer.ai_client import RateLimitExhausted
        try:
            result = self.ai_client.parse(
                system_prompt=self.system_prompt,
                user_prompt=f"Please analyze the following content:\n\n{text}",
                response_format=AIAnalysisResult
            )

            if result:
                relevant = result.relevance_score >= MIN_RELEVANT_SCORE
                mark = ">>>" if relevant else "   "
                logger.info(f"{mark} [{result.relevance_score:>2}/10] {content_id} | {result.reason}")
                return {
                    "relevant": relevant,
                    "relevance_score": result.relevance_score,
                    "summary": result.reason,
                    "category": result.category,
                }
        except RateLimitExhausted:
            raise
        except Exception as e:
            logger.error(f"AI analysis failed for {content_id}: {e}")

        return None


    def generate_daily_summary(self, items: List[Dict[str, Any]]) -> str:
        """Generate a daily AI summary from a list of relevant items."""
        if not items:
            return

        news_list = ""
        for item in items:
            news_list += f"- [{item.get('company')}] {item.get('analysis_summary')} (Score: {item.get('relevance_score')})\n"

        return self.ai_client.completion(
            system_prompt=self.daily_prompt,
            user_prompt=f"Here is the news for today:\n\n{news_list}",
            max_tokens=800
        ) or "Daily summary generation failed."
