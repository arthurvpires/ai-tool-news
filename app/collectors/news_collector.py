import feedparser
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

# List of RSS feeds to monitor
RSS_FEEDS = [
    {"name": "Hacker News AI", "url": "https://hnrss.org/newest?q=AI", "source": "Hacker News"},
    {"name": "Reddit MachineLearning", "url": "https://www.reddit.com/r/MachineLearning/new/.rss", "source": "Reddit"},
    {"name": "Reddit LocalLLaMA", "url": "https://www.reddit.com/r/LocalLLaMA/new/.rss", "source": "Reddit"},
]


class NewsCollector:
    def __init__(self):
        pass

    def fetch_latest_news(self) -> List[Dict[str, Any]]:
        collected = []
        for feed_info in RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_info["url"])
                # Get top 5 recent entries
                for entry in feed.entries[:5]:
                    # Create a unique ID from the link or guid
                    item_id = getattr(entry, "id", entry.link)

                    # Some feeds use summary, some use description
                    description = getattr(entry, "summary", "")
                    if not description:
                        description = getattr(entry, "description", "")

                    collected.append(
                        {
                            "source": feed_info["source"],
                            "company": feed_info["name"],  # Using feed name as company/author equivalent
                            "title": entry.title,
                            "text": f"{entry.title}\n\n{description}",
                            "images": [],  # RSS typically doesn't cleanly expose cover images without html parsing
                            "video": None,
                            "url": entry.link,
                            "id": f"news_{item_id}",
                        }
                    )
            except Exception as e:
                logger.error(f"Error fetching RSS feed {feed_info['name']}: {e}")

        return collected
