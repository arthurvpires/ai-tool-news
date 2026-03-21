from typing import Dict, Any, List, Optional
import logging
import yaml
import json
import os
from pydantic import BaseModel, Field
from app.analyzer.ai_client import AIClient

logger = logging.getLogger(__name__)

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
                self.dedup_prompt = prompts.get("deduplication", {}).get("system_prompt", "")
                self.digest_prompt = prompts.get("digest_summary", {}).get("system_prompt", "")
        except Exception as e:
            logger.error(f"Failed to load prompts.yaml: {e}")
            self.system_prompt = "You are an AI news filter."
            self.dedup_prompt = "Return a JSON list of unique content_ids."
            self.digest_prompt = "Write a numbered digest of the AI news."

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

    def deduplicate(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Use the LLM to detect duplicate events and return only the best item per event.
        Falls back to the original list if the LLM call fails.
        """
        if not items:
            return items

        # Build a compact representation for the LLM
        payload = [
            {
                "content_id": item.get("content_id"),
                "source": item.get("source", ""),
                "source_type": item.get("source_type", "INFLUENCER"),
                "text": (item.get("text") or "")[:300],
                "relevance_score": item.get("relevance_score", 0),
            }
            for item in items
        ]

        user_prompt = (
            "Here are the news items to deduplicate:\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )

        try:
            raw = self.ai_client.completion(
                system_prompt=self.dedup_prompt,
                user_prompt=user_prompt,
                max_tokens=1000,
            )
            if not raw:
                logger.warning("Deduplication LLM returned empty response. Using original list.")
                return items

            # Strip markdown code fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            ids_to_keep = set(json.loads(raw))
            deduped = [item for item in items if item.get("content_id") in ids_to_keep]
            removed = len(items) - len(deduped)
            logger.info(f"Deduplication: {len(items)} → {len(deduped)} items (removed {removed} duplicates)")
            return deduped

        except Exception as e:
            logger.error(f"Deduplication failed: {e}. Using original list.")
            return items

    def rank_and_select(self, items: List[Dict[str, Any]], top_n: int = 10) -> List[Dict[str, Any]]:
        """Sort by relevance_score descending and keep the top N."""
        ranked = sorted(items, key=lambda x: x.get("relevance_score", 0), reverse=True)
        return ranked[:top_n]

    def generate_digest(self, items: List[Dict[str, Any]], window_label: str) -> str:
        """
        Generate a clean, numbered Telegram digest from the selected items.
        Returns the formatted message string.
        """
        if not items:
            return ""

        news_list = ""
        for item in items:
            company = item.get("company") or item.get("source", "Unknown")
            summary = item.get("analysis_summary") or item.get("text", "")[:150]
            score = item.get("relevance_score", 0)
            url = item.get("url", "")

            # Build media indicator tag
            has_video = bool(item.get("video"))
            has_images = bool(item.get("images_json") or item.get("images"))
            if has_video:
                media_tag = f"[🎥]({url})" if url else "🎥"
            elif has_images:
                media_tag = f"[📷]({url})" if url else "📷"
            else:
                media_tag = f"[🔗 See in X]({url})" if url else ""

            tag_part = f" {media_tag}" if media_tag else ""
            news_list += f"- [{company}] {summary} (Score: {score}){tag_part}\n"

        user_prompt = (
            f"Time window: {window_label}\n\n"
            f"News items:\n{news_list}"
        )

        result = self.ai_client.completion(
            system_prompt=self.digest_prompt,
            user_prompt=user_prompt,
            max_tokens=1200,
        )
        return result or "Digest generation failed."
