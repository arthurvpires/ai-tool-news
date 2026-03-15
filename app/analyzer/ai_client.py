import logging
import json
from typing import Optional, List, Dict, Any, Type, TypeVar
from openai import OpenAI
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

class AIClient:
    def __init__(self):
        self.providers = []
        
        # Initialize OpenAI
        if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY != "your_openai_api_key":
            self.providers.append({
                "name": "openai",
                "client": OpenAI(api_key=settings.OPENAI_API_KEY),
                "model": "gpt-4o-mini"
            })

        # Initialize Groq
        if settings.GROQ_API_KEY and settings.GROQ_API_KEY != "your_groq_api_key":
            from groq import Groq
            self.providers.append({
                "name": "groq",
                "client": Groq(api_key=settings.GROQ_API_KEY),
                "model": "llama-3.3-70b-versatile"
            })

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
        """Generic text completion iterating through providers."""
        for p in self.providers:
            try:
                name, client = p["name"], p["client"]
                model = model_override or p["model"]
                
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content
            except Exception as e:
                logger.warning(f"Provider {p['name']} failed: {e}")
        return None

    def parse(self, system_prompt: str, user_prompt: str, response_format: Type[T], max_tokens: int = 500) -> Optional[T]:
        """Structured output parsing iterating through providers."""
        for p in self.providers:
            try:
                name, client = p["name"], p["client"]
                
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
                    # Groq JSON mode logic
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

            except Exception as e:
                logger.warning(f"Provider {name} parse failed: {e}")
