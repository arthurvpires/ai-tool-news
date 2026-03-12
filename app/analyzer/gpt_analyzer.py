from typing import Dict, Any
import logging
from openai import OpenAI
from pydantic import BaseModel, Field
from app.config import settings
import json

import yaml
import os

logger = logging.getLogger(__name__)

class AIAnalysisResult(BaseModel):
    relevant: bool = Field(description="True if the content is an important AI update, False otherwise.")
    reason: str = Field(description="A short explanation of why it is relevant or not.")
    category: str = Field(description="The category of the update.")

class GPTAnalyzer:
    def __init__(self):
        self.client = None
        self.is_groq = False
        
        # Load prompt from YAML
        prompt_path = os.path.join(os.path.dirname(__file__), "prompts.yaml")
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompts = yaml.safe_load(f)
                self.system_prompt = prompts.get("ai_scout", {}).get("system_prompt", "")
        except Exception as e:
            logger.error(f"Failed to load prompts.yaml: {e}")
            self.system_prompt = "You are an AI news filter."

        if settings.OPENAI_API_KEY and settings.OPENAI_API_KEY != "your_openai_api_key":
            self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        elif settings.GROQ_API_KEY and settings.GROQ_API_KEY != "your_groq_api_key":
            from groq import Groq
            self.client = Groq(api_key=settings.GROQ_API_KEY)
            self.is_groq = True
        else:
            logger.warning("No OPENAI_API_KEY or GROQ_API_KEY found. Analyzer will fall back to mocked logic.")

    def analyze(self, content: Dict[str, Any]) -> Dict[str, Any]:
        text = content.get("text", "")
        content_id = content.get("id", "unknown")
        
        logger.info(f"Analyzing content {content_id} (Length: {len(text)})")
        
        if not text:
            logger.warning(f"No text content to analyze for {content_id}")
            return {"relevant": False, "summary": "No text content"}

        if not self.client:
            logger.info(f"Using mocked analysis for {content_id}")
            return self._mock_analyze(text)

        try:
            client_name = "Groq" if self.is_groq else "OpenAI"
            logger.info(f"Dispatching request to {client_name} for {content_id}")
            
            if self.is_groq:
                # Groq using standard chat completion with JSON mode
                response = self.client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {"role": "system", "content": self.system_prompt + "\n\nReturn EXACTLY a valid JSON object with the keys: 'relevant' (boolean), 'reason' (string), and 'category' (string)."},
                        {"role": "user", "content": f"Please analyze the following content:\n\n{text}"}
                    ],
                    response_format={"type": "json_object"},
                    max_tokens=300
                )
                result_json = json.loads(response.choices[0].message.content)
                relevant = bool(result_json.get("relevant"))
                reason = str(result_json.get("reason", result_json.get("summary", "")))
                
                logger.info(f"Analysis result for {content_id}: Relevant={relevant} | Reason: {reason}")
                return {
                    "relevant": relevant,
                    "summary": reason, # we map 'reason' to 'summary' for the rest of the app
                    "category": result_json.get("category", "other")
                }
            else:
                # OpenAI using structured outputs
                response = self.client.beta.chat.completions.parse(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": f"Please analyze the following content:\n\n{text}"}
                    ],
                    response_format=AIAnalysisResult,
                    max_tokens=300
                )

                result: AIAnalysisResult = response.choices[0].message.parsed
                logger.info(f"Analysis result for {content_id}: Relevant={result.relevant} | {result.reason}")
                return {
                    "relevant": result.relevant,
                    "summary": result.reason,
                    "category": result.category
                }
        except Exception as e:
            logger.error(f"GPT Analysis failed for {content.get('id')}: {e}")
            # False on error so we don't spam errors to telegram
            return {"relevant": False, "summary": "Analysis failed"}

    def _mock_analyze(self, text: str) -> Dict[str, Any]:
        """Mock version of analysis when API key is not present."""
        text_lower = text.lower()
        is_relevant = any(keyword in text_lower for keyword in ["release", "launch", "new", "update", "model"])
        
        return {
            "relevant": is_relevant,
            "summary": "Mocked summary: This seems to be an important update." if is_relevant else "Mocked summary: Not important."
        }
