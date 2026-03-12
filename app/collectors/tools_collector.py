from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
import logging

logger = logging.getLogger(__name__)

# Simple scraper for release notes or changelogs
# In a real-world scenario, you might use specific APIs for each tool (like GitHub Releases API)
TOOLS_TO_MONITOR = [
    {
        "name": "LangChain",
        "repo": "langchain-ai/langchain"
    },
    {
        "name": "Ollama",
        "repo": "ollama/ollama"
    }
]

class ToolsCollector:
    def __init__(self):
        self.github_api_url = "https://api.github.com/repos/{}/releases/latest"

    def fetch_latest_updates(self) -> List[Dict[str, Any]]:
        collected = []
        for tool in TOOLS_TO_MONITOR:
            try:
                url = self.github_api_url.format(tool["repo"])
                response = requests.get(url)
                if response.status_code == 200:
                    data = response.json()
                    release_name = data.get("name", data.get("tag_name", "New Release"))
                    body = data.get("body", "")
                    html_url = data.get("html_url", "")
                    release_id = data.get("id")
                    
                    collected.append({
                        "source": "github_releases",
                        "company": tool["name"],
                        "title": f"{tool['name']} Release: {release_name}",
                        "text": f"New version of {tool['name']}: {release_name}\n\n{body[:500]}...", # truncate body
                        "images": [],
                        "video": None,
                        "url": html_url,
                        "id": f"tool_release_{tool['name']}_{release_id}"
                    })
            except Exception as e:
                logger.error(f"Error fetching tool updates for {tool['name']}: {e}")
                
        return collected
