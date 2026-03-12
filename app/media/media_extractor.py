from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger(__name__)

class MediaExtractor:
    def __init__(self):
        pass

    def extract_media(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parses a raw document fetched from the collectors and returns a canonical format
        expected by the analyzer and telegram dispatcher.
        
        Input doc example:
        {
            "source": "twitter",
            "company": "OpenAI",
            "text": "...",
            "images": ["url1", "url2"],
            "video": "url1",
            "url": "https://...",
            "id": "tweet_123"
        }
        """
        try:
            return {
                "id": doc.get("id"),
                "source": doc.get("source"),
                "company": doc.get("company", "Unknown"),
                "text": doc.get("text", doc.get("title", "")),
                "images": doc.get("images", []),
                "video": doc.get("video"),
                "url": doc.get("url")
            }
        except Exception as e:
            logger.error(f"Failed to extract media for document: {e}")
            return {
                "id": "error",
                "source": "error",
                "company": "error",
                "text": "error",
                "images": [],
                "video": None,
                "url": ""
            }
