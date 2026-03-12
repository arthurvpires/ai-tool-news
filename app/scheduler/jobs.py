import logging
import json
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.collectors.twitter_collector import TwitterCollector
from app.media.media_extractor import MediaExtractor
from app.analyzer.gpt_analyzer import GPTAnalyzer
from app.telegram.telegram_sender import TelegramSender
from app.database import db
from app.config import settings

logger = logging.getLogger(__name__)


async def fetch_and_analyze_job():
    """Job 1: Fetch content from collectors and perform AI analysis."""
    logger.info("Starting collection and analysis job...")

    collectors = [TwitterCollector()]
    media_extractor = MediaExtractor()
    analyzer = GPTAnalyzer()

    all_content = []

    # 1. Fetch content from all collectors
    for collector in collectors:
        try:
            if hasattr(collector, "fetch_latest_tweets"):
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
            continue

        # 3. Media Extraction
        canonical_content = media_extractor.extract_media(item)

        # 4. AI Analysis
        analysis_result = analyzer.analyze(canonical_content)

        # Merge all into metadata for saving
        metadata = {**canonical_content, **analysis_result}

        # 5. Save to DB with relevance flag
        db.mark_content_processed(content_id, source, metadata=metadata)

        if analysis_result.get("relevant"):
            logger.info(f"Found relevant content: {content_id}. Queued for sending.")
        else:
            logger.debug(f"Content {content_id} filtered out by AI.")

    logger.info("Collection and analysis job finished.")


async def send_pending_to_telegram_job():
    """Job 2: Send the single most relevant pending item to Telegram."""
    telegram_sender = TelegramSender()

    with db.SessionLocal() as session:
        # Get all currently pending relevant items
        pending_items = (
            session.query(db.ProcessedContent)
            .filter(db.ProcessedContent.is_relevant == True, db.ProcessedContent.sent_at == None)
            .order_by(db.ProcessedContent.relevance_score.desc(), db.ProcessedContent.timestamp.desc())
            .all()
        )

        if not pending_items:
            return

        # Pick only the most relevant one
        top_item = pending_items[0]

        logger.info(
            f"Picking most relevant out of {len(pending_items)} items: {top_item.content_id} (Score: {top_item.relevance_score})"
        )

        try:
            # Reconstruct content and analysis dicts for TelegramSender
            content = {
                "id": top_item.content_id,
                "source": top_item.source,
                "text": top_item.text,
                "company": top_item.company,
                "url": top_item.url,
                "images": json.loads(top_item.images_json) if top_item.images_json else [],
                "video": top_item.video,
            }
            analysis = {"relevant": True, "summary": top_item.analysis_summary, "category": top_item.analysis_category}

            await telegram_sender.send_update(content, analysis)

            # Mark ONLY the top one as sent.
            # The others will stay in the DB and be picked up in the next cycle (1 minute later),
            # effectively sending "only one at a time" as requested.
            top_item.sent_at = datetime.utcnow()
            session.commit()
            logger.info(f"Successfully sent top news: {top_item.content_id}")

        except Exception as e:
            logger.error(f"Failed to send top pending item {top_item.content_id}: {e}")
            session.rollback()


def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    # Job 1: Collect and analyze (every 5-15 mins)
    scheduler.add_job(
        fetch_and_analyze_job,
        "interval",
        minutes=settings.SCHEDULER_SEARCHING_TWEETS_MINUTES,
        id="fetch_and_analyze_job",
        replace_existing=True,
    )

    # Job 2: Send pending items (every 1 min for responsiveness)
    scheduler.add_job(
        send_pending_to_telegram_job,
        "interval",
        minutes=settings.SCHEDULER_TELEGRAM_SENDING_MINUTES,
        id="send_to_telegram_job",
        replace_existing=True,
    )

    return scheduler
