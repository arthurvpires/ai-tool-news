import logging
import json
import asyncio
from datetime import datetime, timezone, timedelta

BRT = timezone(timedelta(hours=-3))
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

def get_window_label() -> str:
    """Return the current BRT date and time as the digest label."""
    now_brt = datetime.now(BRT)
    return now_brt.strftime("%d/%m/%Y %H:%M")

# Window cron definitions (hour, minute in BRT)
WINDOW_CRONS = [
    {"hour": 11, "minute": 30},
    {"hour": 17, "minute": 0},
    {"hour": 20, "minute": 0},
]


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

        try:
            if db.is_content_processed(content_id):
                skipped += 1
                continue
        except Exception as e:
            logger.error(f"DB error checking if processed {content_id}: {e}")
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

        # Persist source_type so deduplication can use it later
        metadata = {**canonical_content, **analysis_result}
        if item.get("source_type"):
            metadata["source_type"] = item["source_type"]

        try:
            db.mark_content_processed(content_id, source, metadata=metadata)
        except Exception as e:
            logger.error(f"DB error marking {content_id} as processed: {e}")

        if analysis_result.get("relevant"):
            relevant += 1

    status = "PAUSED (rate limit)" if rate_limited else "done"
    logger.info(
        f"--- Cycle {status} | Collected: {len(all_content)} | Skipped: {skipped} | Analyzed: {analyzed} | Relevant: {relevant} ---"
    )


async def send_window_digest_job():
    """
    Job 2: Build and send a curated digest for the current time window.
    - Checks backlog of all unsent relevant items.
    - If fewer than MIN_ITEMS_TO_SEND items → skip (carry to next window).
    - Deduplicates with LLM, ranks, selects top 10, generates digest, sends.
    """
    now_brt = datetime.now(BRT)
    window_label = get_window_label()
    logger.info(f"--- Digest job triggered | {window_label} BRT ---")

    pending_items = db.get_pending_items()
    total_pending = len(pending_items)

    if total_pending < settings.MIN_ITEMS_TO_SEND:
        logger.info(
            f"Backlog too small ({total_pending} items, minimum {settings.MIN_ITEMS_TO_SEND}). "
            "Skipping — items carried to next window."
        )
        return

    logger.info(f"Processing {total_pending} pending items for digest...")

    analyzer = AIAnalyzer()

    # Step 1: LLM deduplication
    deduped = analyzer.deduplicate(pending_items)

    # Step 2: Rank and select top 10
    selected = analyzer.rank_and_select(deduped, top_n=10)
    logger.info(f"Selected {len(selected)} items after deduplication + ranking")

    # Step 3: Generate digest text
    digest_text = analyzer.generate_digest(selected, window_label=window_label)
    if not digest_text:
        logger.error("Digest generation returned empty text. Aborting send.")
        return

    # Step 4: Send to Telegram
    telegram_sender = TelegramSender()
    try:
        await telegram_sender.send_digest(digest_text)
        logger.info("Digest sent successfully.")
    except Exception as e:
        logger.error(f"Failed to send digest: {e}")
        return

    # Step 5: Mark all selected items as sent
    sent_ids = [item["content_id"] for item in selected]
    db.mark_items_sent(sent_ids)
    logger.info(f"Marked {len(sent_ids)} items as sent.")


async def cleanup_old_records_job():
    """Job 3: Delete non-relevant records older than N days to keep the DB clean."""
    try:
        deleted = db.delete_old_irrelevant_records(days=settings.DB_CLEANUP_INTERVAL_DAYS)
        if deleted:
            logger.info(f"Cleanup: removed {deleted} old irrelevant record(s).")
    except Exception as e:
        logger.error(f"Cleanup job failed: {e}")


def setup_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=BRT)

    if not settings.ENABLE_SCHEDULER:
        logger.info("All scheduled jobs DISABLED (ENABLE_SCHEDULER=false)")
        return scheduler

    # Job 1 — continuous collection
    scheduler.add_job(
        fetch_and_analyze_job,
        "interval",
        minutes=settings.SCHEDULER_SEARCHING_TWEETS_MINUTES,
        id="fetch_and_analyze_job",
        replace_existing=True,
    )

    # Job 2 — three daily digest windows (BRT)
    windows = [
        {"hour": 11, "minute": 30},
        {"hour": 17, "minute": 0},
        {"hour": 20, "minute": 0},
    ]
    for w in windows:
        scheduler.add_job(
            send_window_digest_job,
            "cron",
            hour=w["hour"],
            minute=w["minute"],
            id=f"digest_{w['hour']}h{w['minute']:02d}",
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info(f"Scheduled digest window: {w['hour']:02d}:{w['minute']:02d} BRT")

    # Job 3 — nightly cleanup
    scheduler.add_job(
        cleanup_old_records_job,
        "cron",
        hour=3,
        minute=0,
        id="cleanup_old_records_job",
        replace_existing=True,
    )

    return scheduler
