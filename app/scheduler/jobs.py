import logging
import json
import asyncio
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))
SEND_HOUR_START = 8
SEND_HOUR_END_WEEKDAY = 19
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

    # Sort content so OFFICIAL sources are processed first
    # This ensures that if both an official source and an influencer are in the same batch,
    # the official one is processed first and the influencer one is marked as a duplicate.
    all_content.sort(key=lambda x: 0 if x.get("source_type") == "OFFICIAL" else 1)

    # Fetch recent relevant items for deduplication
    recent_relevant = db.get_recent_relevant_items(hours=24)

    skipped = 0
    analyzed = 0
    relevant = 0
    duplicates = 0

    for item in all_content:
        content_id = item.get("id")
        source = item.get("source", "unknown")
        source_type = item.get("source_type", "unknown")

        if not content_id:
            continue

        if db.is_content_processed(content_id):
            skipped += 1
            continue

        canonical_content = media_extractor.extract_media(item)
        
        # Deduplication check
        dup_result = analyzer.find_duplicate(canonical_content.get("text", ""), recent_relevant)
        if dup_result.get("is_duplicate"):
            duplicates += 1
            logger.info(f"Duplicate detected: {content_id} is a duplicate of {dup_result.get('duplicate_id')}. Reason: {dup_result.get('reason')}")
            
            # Policy: If we find a duplicate, we skip it.
            # If the NEW item is OFFICIAL and the existing one is NOT, we could swap them,
            # but usually official sources post first or we process them first in this loop.
            # To keep it safe, we mark it as processed but not relevant.
            db.mark_content_processed(content_id, source, metadata={**canonical_content, "relevant": False, "summary": f"Duplicate of {dup_result.get('duplicate_id')}"})
            continue

        analysis_result = analyzer.analyze(canonical_content)
        analyzed += 1
        await asyncio.sleep(2)

        metadata = {**canonical_content, **analysis_result}
        db.mark_content_processed(content_id, source, metadata=metadata)

        if analysis_result.get("relevant"):
            relevant += 1
            # Add to recent relevant for subsequent items in the same batch
            recent_relevant.append({"content_id": content_id, "text": canonical_content.get("text", ""), "source_type": source_type})

    logger.info(
        f"--- Cycle done | Collected: {len(all_content)} | Skipped: {skipped} | Duplicates: {duplicates} | Analyzed: {analyzed} | Relevant: {relevant} ---"
    )


async def send_pending_to_telegram_job():
    """Job 2: Send the single most relevant pending item to Telegram (08h–22h BRT only)."""
    now_brt = datetime.now(BRT)
    is_weekend = now_brt.strftime("%A") in ["Saturday", "Sunday"]

    if is_weekend:
        logger.debug("It's weekend. Skipping regular Telegram updates. Consolidated summary will be sent at 20:00.")
        return

    # Weekdays: 8am to 19pm
    if not (SEND_HOUR_START <= now_brt.hour < SEND_HOUR_END_WEEKDAY):
        logger.debug(f"Outside weekday send window ({now_brt.strftime('%H:%M')} BRT). Skipping.")
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


    except Exception as e:
        logger.error(f"Cleanup job failed: {e}")


async def send_daily_summary_job():
    """Job 5: Generate and send a daily AI summary every Sat/Sun at 20:00 BRT."""
    logger.info("--- Generating Daily AI Summary (Weekend Window) ---")
    
    now_brt = datetime.now(BRT)
    # Window: 00:00 to 19:55 BRT of today
    today_start_brt = now_brt.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start_brt.astimezone(timezone.utc)
    
    # Fetch items since start of today BRT
    recent_items = db.get_relevant_items_since(today_start_utc.isoformat())
    
    if not recent_items:
        logger.info("No relevant items found since 00:00 BRT today.")
        return

    # Filter to only include VERY RELEVANT (e.g., score >= 7)
    very_relevant = [item for item in recent_items if item.get("relevance_score", 0) >= 7]
    
    analyzer = AIAnalyzer()
    summary_content = analyzer.generate_daily_summary(very_relevant if very_relevant else recent_items)

    telegram_sender = TelegramSender()
    try:
        await telegram_sender.bot.send_message(
            chat_id=settings.TELEGRAM_CHAT_ID,
            text=summary_content,
            parse_mode="Markdown"
        )
        logger.info("Daily summary sent successfully.")
    except Exception as e:
        logger.error(f"Failed to send daily summary: {e}")


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

    # Job 2: Send pending items to Telegram (8h–20h BRT only)
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


    # Job 5: Daily Summary (Saturday and Sunday at 20:00 BRT)
    scheduler.add_job(
        send_daily_summary_job,
        "cron",
        day_of_week="sat,sun",
        hour=20,
        minute=0,
        id="daily_summary_job",
        replace_existing=True,
    )

    return scheduler
