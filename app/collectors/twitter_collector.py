from typing import List, Dict, Any
import feedparser
import logging
import re
import time
from datetime import datetime, timezone
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# List of RSS feeds to monitor using nitter proxies
# Nitter instances are notoriously unstable, so we use a pool
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.cz",
    "https://nitter.privacydev.net",
    "https://nitter.no-logs.com"
]

COMPANIES = {
    "@OpenAI": "OpenAI",
    "@AnthropicAI": "AnthropicAI",
    "@ClaudeAI": "ClaudeAI",
    "@perplexity_ai": "perplexity_ai",
    "@Google": "Google",
    "@GeminiApp": "GeminiApp",
    "@sama": "sama"
}

class TwitterCollector:
    def __init__(self):
        pass
    
    def fetch_latest_tweets(self) -> List[Dict[str, Any]]:
        return self._fetch_from_rss()

    def _fetch_from_rss(self) -> List[Dict[str, Any]]:
        collected = []
        now = datetime.now(timezone.utc)
        
        for handle, username in COMPANIES.items():
            success = False
            for instance in NITTER_INSTANCES:
                rss_url = f"{instance}/{username}/rss"
                try:
                    logger.info(f"Fetching tweets for {handle} from {rss_url}...")
                    feed = feedparser.parse(rss_url)
                    
                    if not feed.entries:
                        logger.warning(f"No entries for {handle} at {instance}")
                        continue
                        
                    logger.info(f"Processing {len(feed.entries)} entries for {handle}")
                    for entry in feed.entries[:10]: # Check more entries to find recent ones
                        
                        # Filter out retweets and replies
                        if entry.title.startswith("RT by") or "RT @" in entry.title:
                            continue
                        if entry.title.startswith("R to @") or "R to @" in entry.title:
                            continue

                        # Last 24 hours filter
                        if hasattr(entry, 'published_parsed') and entry.published_parsed:
                            pub_time = time.mktime(entry.published_parsed)
                            pub_dt = datetime.fromtimestamp(pub_time, tz=timezone.utc)
                            diff = now - pub_dt
                            if diff.total_seconds() > 24 * 3600:
                                logger.debug(f"Skipping old tweet from {handle} ({diff.total_seconds()/3600:.1f}h ago)")
                                continue
                        else:
                            continue

                        tweet_url = entry.link.replace(instance, "x.com").split("#")[0]
                        tweet_id = tweet_url.split("/")[-1]
                        
                        raw_html = getattr(entry, "summary", getattr(entry, "description", ""))
                        soup = BeautifulSoup(raw_html, "html.parser")
                        
                        # Cleanup text
                        text = soup.get_text(separator="\n")
                        
                        # Remove instance-specific footers (e.g., Hydejack, etc.)
                        text = re.split(r'Try Hydejack|Hydejack Logo', text)[0]
                        
                        text = re.sub(r'[ \t]+', ' ', text)
                        text = re.sub(r'\n\s*\n', '\n\n', text)
                        text = re.sub(r'\n{3,}', '\n\n', text)
                        text = text.strip()
                        
                        images = []
                        video_url = None
                        
                        # 1. Check for video in enclosures
                        if hasattr(entry, 'enclosures'):
                            for enclosure in entry.enclosures:
                                if enclosure.type.startswith('video') or enclosure.href.endswith(('.mp4', '.m4v', '.webm')):
                                    video_url = enclosure.href
                                    break
                        
                        # 2. Extract media from HTML summary
                        # First, find all links and check if they look like video files
                        for a in soup.find_all('a'):
                            href = a.get('href', '')
                            if any(href.endswith(ext) for ext in ['.mp4', '.m4v', '.webm']):
                                video_url = href
                                break
                            if 'video' in a.get('class', []):
                                video_url = href
                                break

                        if not video_url:
                            video_tag = soup.find('video')
                            if video_tag:
                                source_tag = video_tag.find('source')
                                if source_tag and source_tag.get('src'):
                                    video_url = source_tag.get('src')
                                elif video_tag.get('src'):
                                    video_url = video_tag.get('src')
                        
                        # Direct check for video links in soup
                        if not video_url:
                            for source in soup.find_all('source'):
                                if source.get('src') and any(source.get('src').endswith(ext) for ext in ['.mp4', '.m4v', '.webm']):
                                    video_url = source.get('src')
                                    break

                        # Handle relative URLs
                        if video_url and video_url.startswith("/"):
                            video_url = instance + video_url
                        
                        for img in soup.find_all('img'):
                            src = img.get('src')
                            if src and "profile_images" not in src:
                                if src.startswith("/"):
                                    src = instance + src
                                images.append(src)
                        
                        # If video found, or if text contains "Video", flag it for yt-dlp
                        # Nitter often labels video tweets with the word "Video" in the content
                        if video_url or "Video" in text:
                            video_detected = True
                        else:
                            video_detected = False

                        if video_detected:
                            text = re.sub(r'\s+Video$', '', text, flags=re.IGNORECASE).strip()
                            logger.info(f"VIDEO FLAG set for tweet {tweet_id}")
                                
                        collected.append({
                            "source": "twitter",
                            "company": handle,
                            "text": text,
                            "images": images,
                            "video": tweet_url if video_detected else None, # Use tweet URL as the video source for yt-dlp
                            "url": tweet_url,
                            "id": f"tweet_{tweet_id}"
                        })
                    
                    success = True
                    break # Success with this instance, move to next handle
                    
                except Exception as e:
                    logger.error(f"Failed to fetch {handle} from {instance}: {e}")
            
            if not success:
                logger.error(f"All instances failed for {handle}")
                
        return collected

    def _mock_tweets(self) -> List[Dict[str, Any]]:
        return [
            {
                "source": "twitter",
                "company": "OpenAI",
                "text": "Today we are launching a new version of our reasoning models! It brings massive improvements.",
                "images": [],
                "video": None,
                "url": "https://x.com/OpenAI/status/mocked123",
                "id": "tweet_mocked123_rss"
            }
        ]
