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
from app.analyzer.ai_client import RateLimitExhausted
from app.telegram.telegram_sender import TelegramSender
from app.database import db
from app.config import settings

logger = logging.getLogger(__name__)

_rate_limit_until = None


async def fetch_and_analyze_job():
    """Job 1: Fetch content from collectors and perform AI analysis."""
    global _rate_limit_until

    if _rate_limit_until and datetime.now(timezone.utc) < _rate_limit_until:
        remaining = (_rate_limit_until - datetime.now(timezone.utc)).total_seconds() / 60
        logger.info(f"--- Cycle skipped (rate limit cooldown, {remaining:.0f}min remaining) ---")
        return

    _rate_limit_until = None
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

    all_content.sort(key=lambda x: 0 if x.get("source_type") == "OFFICIAL" else 1)

    skipped = 0
    analyzed = 0
    relevant = 0

    rate_limited = False

    for item in all_content:
        content_id = item.get("id")
        source = item.get("source", "unknown")

        if not content_id:
            continue

        if db.is_content_processed(content_id):
            skipped += 1
            continue

        canonical_content = media_extractor.extract_media(item)

        await asyncio.sleep(6)

        try:
            analysis_result = analyzer.analyze(canonical_content)
        except RateLimitExhausted as e:
            import re
            mins = re.search(r"Retry in (\d+)min", str(e))
            cooldown = int(mins.group(1)) + 2 if mins else 15
            _rate_limit_until = datetime.now(timezone.utc) + timedelta(minutes=cooldown)
            logger.warning(f"Stopping cycle: {e} (cooldown {cooldown}min)")
            rate_limited = True
            break

        if not analysis_result:
            logger.warning(f"Analysis failed for {content_id}. Skipping.")
            continue

        analyzed += 1

        metadata = {**canonical_content, **analysis_result}
        db.mark_content_processed(content_id, source, metadata=metadata)

        if analysis_result.get("relevant"):
            relevant += 1

    status = "PAUSED (rate limit)" if rate_limited else "done"
    logger.info(
        f"--- Cycle {status} | Collected: {len(all_content)} | Skipped: {skipped} | Analyzed: {analyzed} | Relevant: {relevant} ---"
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

        # Mark all items from today as sent so they aren't resent individually on Monday
        for item in recent_items:
            db.mark_item_sent(item["content_id"])
        logger.info(f"Marked {len(recent_items)} items as sent.")

    except Exception as e:
        logger.error(f"Failed to send daily summary: {e}")


def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    if not settings.ENABLE_SCHEDULER:
        logger.info("All scheduled jobs DISABLED (ENABLE_SCHEDULER=false)")
        return scheduler

    scheduler.add_job(
        fetch_and_analyze_job,
        "interval",
        minutes=settings.SCHEDULER_SEARCHING_TWEETS_MINUTES,
        id="fetch_and_analyze_job",
        replace_existing=True,
    )

    scheduler.add_job(
        send_pending_to_telegram_job,
        "interval",
        minutes=settings.SCHEDULER_TELEGRAM_SENDING_MINUTES,
        id="send_to_telegram_job",
        replace_existing=True,
        misfire_grace_time=120,
    )

    scheduler.add_job(
        cleanup_old_records_job,
        "cron",
        hour=3,
        minute=0,
        id="cleanup_old_records_job",
        replace_existing=True,
    )

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
