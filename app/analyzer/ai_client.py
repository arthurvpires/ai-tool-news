import logging
import re
from typing import Optional, Type, TypeVar
from openai import OpenAI
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

class RateLimitExhausted(Exception):
    """Raised on any 429 rate limit — stops the cycle immediately."""
    pass


def _extract_wait_minutes(error_msg):
    match = re.search(r"try again in (\d+)m(\d+\.?\d*)s", str(error_msg))
    if match:
        return int(match.group(1)) + 1
    match = re.search(r"try again in (\d+\.?\d*)s", str(error_msg))
    if match:
        return max(1, int(float(match.group(1)) / 60) + 1)
    return 5


def _is_rate_limit(e):
    return "429" in str(e) or "rate_limit" in str(e).lower()


GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]


class AIClient:
    def __init__(self):
        self.providers = []
        
        if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY not in ["", "your_openai_api_key"]:
            self.providers.append({
                "name": "openai",
                "client": OpenAI(api_key=settings.OPENAI_API_KEY),
                "model": "gpt-4o-mini"
            })
            logger.info("OpenAI provider initialized.")
            
        if settings.GROQ_API_KEY and settings.GROQ_API_KEY not in ["", "your_groq_api_key"]:
            from groq import Groq
            groq_client = Groq(api_key=settings.GROQ_API_KEY)
            for model in GROQ_MODELS:
                self.providers.append({
                    "name": f"groq/{model}",
                    "client": groq_client,
                    "model": model,
                    "type": "groq",
                })
            logger.info(f"Groq provider initialized with {len(GROQ_MODELS)} models.")

        if not self.providers:
            logger.warning("No valid OpenAI or Groq API key found.")

    def completion(self, system_prompt: str, user_prompt: str, max_tokens: int = 1000, model_override: Optional[str] = None) -> Optional[str]:
        last_rate_limit = None
        for p in self.providers:
            try:
                model = model_override or p["model"]
                response = p["client"].chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content
            except Exception as e:
                if _is_rate_limit(e):
                    wait_min = _extract_wait_minutes(e)
                    logger.warning(f"Rate limit on {p['name']}. Trying next model...")
                    last_rate_limit = f"All models rate-limited. Last: {p['name']} ({wait_min}min)."
                    continue
                logger.warning(f"Provider {p['name']} failed: {e}")
        if last_rate_limit:
            raise RateLimitExhausted(last_rate_limit)
        return None

    def parse(self, system_prompt: str, user_prompt: str, response_format: Type[T], max_tokens: int = 500) -> Optional[T]:
        last_rate_limit = None
        for p in self.providers:
            name = p["name"]
            provider_type = p.get("type", name)
            try:
                if provider_type == "openai":
                    response = p["client"].beta.chat.completions.parse(
                        model=p["model"],
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        response_format=response_format,
                        max_tokens=max_tokens,
                    )
                    return response.choices[0].message.parsed

                if provider_type == "groq":
                    json_instruction = "\n\nReturn ONLY a valid JSON object matching the requested schema."
                    response = p["client"].chat.completions.create(
                        model=p["model"],
                        messages=[
                            {"role": "system", "content": system_prompt + json_instruction},
                            {"role": "user", "content": user_prompt},
                        ],
                        response_format={"type": "json_object"},
                        max_tokens=max_tokens,
                    )
                    return response_format.model_validate_json(response.choices[0].message.content)

            except Exception as e:
                if _is_rate_limit(e):
                    wait_min = _extract_wait_minutes(e)
                    logger.warning(f"Rate limit on {name}. Trying next model...")
                    last_rate_limit = f"All models rate-limited. Last: {name} ({wait_min}min)."
                    continue
                logger.warning(f"Provider {name} parse failed: {e}")
        if last_rate_limit:
            raise RateLimitExhausted(last_rate_limit)
        return None
