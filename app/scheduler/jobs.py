import logging
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.collectors.twitter_collector import TwitterCollector
from app.media.media_extractor import MediaExtractor
from app.analyzer.gpt_analyzer import GPTAnalyzer
from app.telegram.telegram_sender import TelegramSender
from app.database import db

logger = logging.getLogger(__name__)

async def run_all_collectors():
    """Main job executed by the scheduler."""
    logger.info("Starting collector job...")
    
    collectors = [
        TwitterCollector()
    ]
    
    media_extractor = MediaExtractor()
    analyzer = GPTAnalyzer()
    telegram_sender = TelegramSender()
    
    all_content = []
    
    # 1. Fetch content from all collectors
    for collector in collectors:
        try:
            if hasattr(collector, 'fetch_latest_tweets'):
                all_content.extend(collector.fetch_latest_tweets())
        except Exception as e:
            logger.error(f"Error running collector {collector.__class__.__name__}: {e}")

    logger.info(f"Collected total of {len(all_content)} items.")

    for item in all_content:
        content_id = item.get("id")
        source = item.get("source", "unknown")

        if not content_id:
            continue

        # 2. Anti Duplication System
        if db.is_content_processed(content_id):
            logger.debug(f"Content {content_id} already processed. Skipping.")
            continue

        # 3. Media Extraction
        canonical_content = media_extractor.extract_media(item)

        # 4. AI Analysis
        analysis_result = analyzer.analyze(canonical_content)

        # 5. Filter for relevance
        if analysis_result.get("relevant"):
            logger.info(f"Found relevant content: {content_id}. Sending to Telegram...")
            # 6. Message Construction & Telegram Publishing
            await telegram_sender.send_update(canonical_content, analysis_result)
        else:
            logger.info(f"Content {content_id} filtered out by AI: {analysis_result.get('summary')}")

        # Mark as processed regardless so we don't re-analyze
        db.mark_content_processed(content_id, source)

    logger.info("Collector job finished.")

def setup_scheduler() -> AsyncIOScheduler:
    from app.config import settings
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_all_collectors, 
        'interval', 
        minutes=settings.SCHEDULER_INTERVAL_MINUTES,
        id="run_collectors_job",
        replace_existing=True
    )
    return scheduler
