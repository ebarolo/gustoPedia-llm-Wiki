import logging

from supabase import Client

from social_ingestion.models import JobStatus

logger = logging.getLogger(__name__)

_TABLE = "recipe_ingestion_jobs"


def create_job(db: Client, url: str) -> str:
    """Insert a new pending job and return its id."""
    resp = (
        db.table(_TABLE)
        .insert({"url": url, "status": JobStatus.PENDING.value})
        .execute()
    )
    return resp.data[0]["id"]


def set_processing(db: Client, job_id: str) -> None:
    db.table(_TABLE).update({"status": JobStatus.PROCESSING.value}).eq("id", job_id).execute()


def set_completed(db: Client, job_id: str, recipe_id: str) -> None:
    db.table(_TABLE).update(
        {"status": JobStatus.COMPLETED.value, "recipe_id": recipe_id}
    ).eq("id", job_id).execute()


def set_error(db: Client, job_id: str, message: str) -> None:
    db.table(_TABLE).update(
        {"status": JobStatus.ERROR.value, "error_message": message}
    ).eq("id", job_id).execute()


def append_log(db: Client, job_id: str, level: str, msg: str) -> None:
    try:
        db.rpc(
            "append_ingestion_log",
            {
                "job_id": job_id,
                "log_message": f"[{level.upper()}][GustoPedia] {msg}",
            },
        ).execute()
    except Exception:
        logger.warning("append_log failed for job_id=%s: %s", job_id, msg)


def url_exists(db: Client, url: str) -> bool:
    resp = db.table(_TABLE).select("id").eq("url", url).limit(1).execute()
    return bool(resp.data)
