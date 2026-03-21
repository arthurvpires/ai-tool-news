from datetime import datetime, timedelta
from supabase import create_client
from app.config import settings
import logging
import json

logger = logging.getLogger(__name__)

TABLE = "processed_content"

supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


def is_content_processed(content_id):
    result = (
        supabase.table(TABLE)
        .select("content_id")
        .eq("content_id", content_id)
        .execute()
    )
    return len(result.data) > 0


def mark_content_processed(content_id, source, metadata=None):
    if is_content_processed(content_id):
        return

    row = {
        "content_id": content_id,
        "source": source,
    }

    if metadata:
        sent_at = metadata.pop("sent_at", None)
        if sent_at:
            row["sent_at"] = sent_at.isoformat() if isinstance(sent_at, datetime) else sent_at

        row["is_relevant"] = metadata.get("relevant", False)
        row["relevance_score"] = metadata.get("relevance_score", 0)
        row["text"] = metadata.get("text")
        row["company"] = metadata.get("company")
        row["url"] = metadata.get("url")
        if metadata.get("images"):
            row["images_json"] = json.dumps(metadata.get("images"))
        row["video"] = metadata.get("video")
        row["analysis_summary"] = metadata.get("summary")
        row["analysis_category"] = metadata.get("category")
        if metadata.get("source_type"):
            row["source_type"] = metadata.get("source_type")

    supabase.table(TABLE).insert(row).execute()


def get_pending_items():
    result = (
        supabase.table(TABLE)
        .select("*")
        .eq("is_relevant", True)
        .is_("sent_at", "null")
        .order("relevance_score", desc=True)
        .order("timestamp", desc=True)
        .execute()
    )
    return result.data


def mark_item_sent(content_id):
    supabase.table(TABLE).update(
        {"sent_at": datetime.utcnow().isoformat()}
    ).eq("content_id", content_id).execute()


def mark_items_sent(content_ids: list):
    """Bulk-mark a list of content_ids as sent."""
    if not content_ids:
        return
    now = datetime.utcnow().isoformat()
    for cid in content_ids:
        supabase.table(TABLE).update({"sent_at": now}).eq("content_id", cid).execute()


def delete_old_irrelevant_records(days: int = 2) -> int:
    """Delete non-relevant records older than `days` days. Returns number of deleted rows."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    result = (
        supabase.table(TABLE)
        .delete()
        .eq("is_relevant", False)
        .lt("timestamp", cutoff)
        .execute()
    )
    return len(result.data) if result.data else 0


def get_relevant_items_since(since_iso: str):
    """Fetch relevant items since a specific ISO format timestamp."""
    result = (
        supabase.table(TABLE)
        .select("*")
        .eq("is_relevant", True)
        .gte("timestamp", since_iso)
        .order("timestamp", desc=True)
        .execute()
    )
    return result.data


def update_is_relevant(content_id, is_relevant):
    supabase.table(TABLE).update(
        {"is_relevant": is_relevant}
    ).eq("content_id", content_id).execute()


def get_total_count():
    result = (
        supabase.table(TABLE)
        .select("content_id", count="exact")
        .execute()
    )
    return result.count or 0
