# gnammyWiki/wiki/worker.py
import asyncio
import logging

from supabase import Client

from wiki import job_manager
from wiki.service import WikiIngestionService

logger = logging.getLogger(__name__)

# Drain seriale per processo (equivalente del per-project lock di llm_wiki):
# una ricetta tocca 5-15 pagine, ingest concorrenti sulle stesse pagine si
# pestano. La claim RPC (FOR UPDATE SKIP LOCKED) rende safe anche più istanze.
_drain_lock = asyncio.Lock()


async def drain(db: Client) -> int:
    """Drena la coda finché claim_job restituisce righe. Ritorna i job processati."""
    if _drain_lock.locked():
        logger.info("Drain già in corso: kick ignorato.")
        return 0

    processed = 0
    async with _drain_lock:
        service = WikiIngestionService(db)
        while True:
            job = job_manager.claim_job(db)
            if job is None:
                break
            processed += 1
            job_id = job["id"]
            try:
                pages_touched = await service.ingest_recipe(job_id, job["recipe_id"])
                job_manager.set_completed(db, job_id, pages_touched)
            except Exception as exc:
                logger.exception("Wiki ingest fallito job_id=%s", job_id)
                job_manager.append_log(db, job_id, "error", str(exc))
                if job.get("attempts", 0) >= job_manager.MAX_ATTEMPTS:
                    job_manager.set_error(db, job_id, str(exc))
                else:
                    job_manager.set_pending(db, job_id)
    return processed
