# gnammyWiki/wiki/job_manager.py
import logging
from typing import Any, Optional

from supabase import Client

from wiki.models import WikiJobStatus

logger = logging.getLogger(__name__)

_TABLE = "wiki_ingestion_jobs"
MAX_ATTEMPTS = 3


def claim_job(db: Client) -> Optional[dict[str, Any]]:
    """Claim atomico via RPC (FOR UPDATE SKIP LOCKED). None se coda vuota."""
    resp = db.rpc("claim_wiki_ingestion_job", {}).execute()
    return resp.data[0] if resp.data else None


def enqueue(db: Client, recipe_id: str) -> Optional[str]:
    """Accoda un job pending per la ricetta. None se esiste già un job vivo."""
    try:
        resp = db.table(_TABLE).insert({"recipe_id": recipe_id}).execute()
        return resp.data[0]["id"]
    except Exception as exc:
        # 23505 = violazione dell'unique parziale sui job vivi: dedup, non errore
        if "23505" in str(exc) or "duplicate" in str(exc).lower():
            return None
        raise


def set_completed(db: Client, job_id: str, pages_touched: list[str]) -> None:
    db.table(_TABLE).update(
        {"status": WikiJobStatus.COMPLETED.value, "pages_touched": pages_touched}
    ).eq("id", job_id).execute()


def set_error(db: Client, job_id: str, message: str) -> None:
    db.table(_TABLE).update(
        {"status": WikiJobStatus.ERROR.value, "error_message": message}
    ).eq("id", job_id).execute()


def set_pending(db: Client, job_id: str) -> None:
    """Rimette il job in coda per un nuovo tentativo."""
    db.table(_TABLE).update({"status": WikiJobStatus.PENDING.value}).eq("id", job_id).execute()


def count_pending(db: Client) -> int:
    resp = (
        db.table(_TABLE)
        .select("id", count="exact")
        .eq("status", WikiJobStatus.PENDING.value)
        .execute()
    )
    return resp.count or 0


def get_job(db: Client, job_id: str) -> Optional[dict[str, Any]]:
    resp = db.table(_TABLE).select("*").eq("id", job_id).limit(1).execute()
    return resp.data[0] if resp.data else None


def append_log(db: Client, job_id: str, level: str, msg: str) -> None:
    try:
        db.rpc(
            "append_wiki_ingestion_log",
            {
                "job_id": job_id,
                "log_message": f"[{level.upper()}][gnammyWiki] {msg}",
            },
        ).execute()
    except Exception:
        logger.warning("append_log failed for job_id=%s: %s", job_id, msg)
