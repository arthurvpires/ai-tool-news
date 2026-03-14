import logging
import json
import asyncio
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))
SEND_HOUR_START = 8
SEND_HOUR_END = 22
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.collectors.twitter_collector import TwitterCollector
from app.media.media_extractor import MediaExtractor
from app.analyzer.ai_analyzer import AIAnalyzer
from app.telegram.telegram_sender import TelegramSender
from app.database import db
from app.config import settings

logger = logging.getLogger(__name__)


async def fetch_and_analyze_job():
    """Job 1: Fetch content from collectors and perform AI analysis."""
    logger.info("--- Collection cycle started ---")

    collectors = [TwitterCollector()]
    media_extractor = MediaExtractor()
    analyzer = AIAnalyzer()

    all_content = []
    for collector in collectors:
        try:
            if hasattr(collector, "fetch_latest_tweets"):
                all_content.extend(collector.fetch_latest_tweets())
        except Exception as e:
            logger.error(f"Collector {collector.__class__.__name__} failed: {e}")

    skipped = 0
    analyzed = 0
    relevant = 0

    for item in all_content:
        content_id = item.get("id")
        source = item.get("source", "unknown")

        if not content_id:
            continue

        if db.is_content_processed(content_id):
            skipped += 1
            continue

        canonical_content = media_extractor.extract_media(item)
        analysis_result = analyzer.analyze(canonical_content)
        analyzed += 1
        await asyncio.sleep(2)

        metadata = {**canonical_content, **analysis_result}
        db.mark_content_processed(content_id, source, metadata=metadata)

        if analysis_result.get("relevant"):
            relevant += 1

    logger.info(
        f"--- Cycle done | Collected: {len(all_content)} | Skipped: {skipped} | Analyzed: {analyzed} | Relevant: {relevant} ---"
    )


async def send_pending_to_telegram_job():
    """Job 2: Send the single most relevant pending item to Telegram (08h–22h BRT only)."""
    now_brt = datetime.now(BRT)
    if not (SEND_HOUR_START <= now_brt.hour < SEND_HOUR_END):
        logger.debug(f"Outside send window ({now_brt.strftime('%H:%M')} BRT). Skipping.")
        return

    telegram_sender = TelegramSender()

    pending_items = db.get_pending_items()

    if not pending_items:
        return

    top_item = pending_items[0]

    logger.info(
        f"Sending to Telegram ({len(pending_items)} pending) | {top_item['company']} | Score: {top_item['relevance_score']} | {top_item['content_id']}"
    )

    try:
        content = {
            "id": top_item["content_id"],
            "source": top_item["source"],
            "text": top_item["text"],
            "company": top_item["company"],
            "url": top_item["url"],
            "images": json.loads(top_item["images_json"]) if top_item.get("images_json") else [],
            "video": top_item["video"],
        }
        analysis = {
            "relevant": True,
            "summary": top_item["analysis_summary"],
            "category": top_item["analysis_category"],
        }

        await telegram_sender.send_update(content, analysis)

        db.mark_item_sent(top_item["content_id"])
        logger.info(f"Sent OK: {top_item['content_id']}")

    except Exception as e:
        logger.error(f"Send FAILED: {top_item['content_id']} | {e}")


async def cleanup_old_records_job():
    """Job 3: Delete non-relevant records older than 24h to keep the DB clean."""
    try:
        deleted = db.delete_old_irrelevant_records(days=settings.DB_CLEANUP_INTERVAL_DAYS)
        if deleted:
            logger.info(f"Cleanup: removed {deleted} old irrelevant record(s).")
    except Exception as e:
        logger.error(f"Cleanup job failed: {e}")


def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    # Job 1: Collect and analyze
    scheduler.add_job(
        fetch_and_analyze_job,
        "interval",
        minutes=settings.SCHEDULER_SEARCHING_TWEETS_MINUTES,
        id="fetch_and_analyze_job",
        replace_existing=True,
    )

    # Job 2: Send pending items to Telegram (8h–22h BRT only)
    scheduler.add_job(
        send_pending_to_telegram_job,
        "interval",
        minutes=settings.SCHEDULER_TELEGRAM_SENDING_MINUTES,
        id="send_to_telegram_job",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # Job 3: Cleanup old irrelevant records (daily at 00:00 BRT)
    scheduler.add_job(
        cleanup_old_records_job,
        "cron",
        hour=3,
        minute=0,
        id="cleanup_old_records_job",
        replace_existing=True,
    )

    return scheduler
