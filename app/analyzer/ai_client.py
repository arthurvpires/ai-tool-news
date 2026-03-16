import logging
import json
import re
import time
from typing import Optional, List, Dict, Any, Type, TypeVar
from openai import OpenAI
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

MAX_RETRIES = 2
SHORT_LIMIT_MAX_WAIT = 30
DAILY_LIMIT_THRESHOLD = 120


class RateLimitExhausted(Exception):
    """Raised when rate limit wait time is too long (daily quota hit)."""
    pass


def _extract_wait_seconds(error_msg):
    match = re.search(r"try again in (\d+)m(\d+\.?\d*)s", str(error_msg))
    if match:
        return int(match.group(1)) * 60 + float(match.group(2))
    match = re.search(r"try again in (\d+\.?\d*)s", str(error_msg))
    if match:
        return float(match.group(1))
    return 30


def _is_rate_limit(e):
    return "429" in str(e) or "rate_limit" in str(e).lower()


def _handle_rate_limit(e, provider_name, attempt, max_retries):
    wait = _extract_wait_seconds(e)
    if wait > DAILY_LIMIT_THRESHOLD:
        raise RateLimitExhausted(f"Daily limit reached for {provider_name}. Retry in {wait/60:.0f}min.")
    if attempt < max_retries:
        capped = min(wait, SHORT_LIMIT_MAX_WAIT)
        logger.warning(f"Rate limit hit ({provider_name}). Waiting {capped:.0f}s...")
        time.sleep(capped)
        return True
    return False


class AIClient:
    def __init__(self):
        self.providers = []
        
        # Initialize OpenAI if key is present and valid
        if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY not in ["", "your_openai_api_key"]:
            self.providers.append({
                "name": "openai",
                "client": OpenAI(api_key=settings.OPENAI_API_KEY),
                "model": "gpt-4o-mini"
            })
            logger.info("OpenAI provider initialized.")
            
        # Otherwise, initialize Groq if key is present and valid
        elif settings.GROQ_API_KEY and settings.GROQ_API_KEY not in ["", "your_groq_api_key"]:
            from groq import Groq
            self.providers.append({
                "name": "groq",
                "client": Groq(api_key=settings.GROQ_API_KEY),
                "model": "llama-3.3-70b-versatile"
            })
        else:
            logger.warning("No valid OpenAI or Groq API key found.")

    @property
    def openai_client(self):
        """Helper to check if OpenAI is available for specific beta features."""
        for p in self.providers:
            if p["name"] == "openai": return p["client"]
        return None

    @property
    def groq_client(self):
        """Helper to check if Groq is available."""
        for p in self.providers:
            if p["name"] == "groq": return p["client"]
        return None

    def completion(self, system_prompt: str, user_prompt: str, max_tokens: int = 1000, model_override: Optional[str] = None) -> Optional[str]:
        for p in self.providers:
            for attempt in range(MAX_RETRIES + 1):
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
                except RateLimitExhausted:
                    raise
                except Exception as e:
                    if _is_rate_limit(e):
                        if _handle_rate_limit(e, p["name"], attempt, MAX_RETRIES):
                            continue
                    logger.warning(f"Provider {p['name']} failed: {e}")
                    break
        return None

    def parse(self, system_prompt: str, user_prompt: str, response_format: Type[T], max_tokens: int = 500) -> Optional[T]:
        for p in self.providers:
            name, client = p["name"], p["client"]
            for attempt in range(MAX_RETRIES + 1):
                try:
                    if name == "openai":
                        response = client.beta.chat.completions.parse(
                            model=p["model"],
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt},
                            ],
                            response_format=response_format,
                            max_tokens=max_tokens,
                        )
                        return response.choices[0].message.parsed

                    if name == "groq":
                        json_instruction = "\n\nReturn ONLY a valid JSON object matching the requested schema."
                        response = client.chat.completions.create(
                            model=p["model"],
                            messages=[
                                {"role": "system", "content": system_prompt + json_instruction},
                                {"role": "user", "content": user_prompt},
                            ],
                            response_format={"type": "json_object"},
                            max_tokens=max_tokens,
                        )
                        return response_format.model_validate_json(response.choices[0].message.content)

                except RateLimitExhausted:
                    raise
                except Exception as e:
                    if _is_rate_limit(e):
                        if _handle_rate_limit(e, name, attempt, MAX_RETRIES):
                            continue
                    logger.warning(f"Provider {name} parse failed: {e}")
                    break
        return None
