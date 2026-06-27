# gnammyWiki/wiki/worker.py
import asyncio
import logging
import time

from supabase import Client

from wiki import job_manager
from wiki.service import WikiIngestionService

logger = logging.getLogger(__name__)

# Budget di tempo del drain sincrono: il drain gira DENTRO la richiesta HTTP
# /wiki/process-queue (la CPU di Cloud Run resta allocata finché l'handler non
# ritorna), quindi va chiuso prima del request timeout. Default Cloud Run = 300s;
# 180s lascia margine per finire l'ultimo job già claimato (~60-90s l'uno).
# I job rimasti pending sono drenati dal kick successivo (uno per job inserito)
# o, come backstop, dalla crash-recovery a 15 min della claim RPC.
DEFAULT_DRAIN_BUDGET_SECONDS = 180

# Drain seriale per processo (equivalente del per-project lock di llm_wiki):
# una ricetta tocca 5-15 pagine, ingest concorrenti sulle stesse pagine si
# pestano. La claim RPC (FOR UPDATE SKIP LOCKED) rende safe anche più istanze.
_drain_lock = asyncio.Lock()


async def drain(
    db: Client,
    max_jobs: int | None = None,
    max_seconds: float | None = None,
) -> int:
    """Drena la coda finché claim_job restituisce righe. Ritorna i job processati.

    Sincrono e bounded: pensato per essere awaitato dentro la richiesta HTTP,
    NON lanciato in background (su Cloud Run un task di sfondo viene congelato
    quando la response parte → job bloccati su 'processing'). Si ferma quando la
    coda è vuota, o dopo `max_jobs` job, o oltre `max_seconds` di budget.
    """
    if _drain_lock.locked():
        logger.info("Drain già in corso: kick ignorato.")
        return 0

    processed = 0
    started = time.monotonic()
    async with _drain_lock:
        service = WikiIngestionService(db)
        while not _budget_reached(processed, max_jobs, started, max_seconds):
            job = job_manager.claim_job(db)
            if job is None:
                break
            processed += 1
            await _process_job(db, service, job)
    return processed


def _budget_reached(
    processed: int,
    max_jobs: int | None,
    started: float,
    max_seconds: float | None,
) -> bool:
    """True se va fermato il drain: cap job raggiunto o budget tempo esaurito."""
    if max_jobs is not None and processed >= max_jobs:
        logger.info("Drain: raggiunto cap di %d job.", max_jobs)
        return True
    if max_seconds is not None and (time.monotonic() - started) >= max_seconds:
        logger.info("Drain: budget tempo esaurito (%ss), resto alla coda.", max_seconds)
        return True
    return False


async def _process_job(db: Client, service: WikiIngestionService, job: dict) -> None:
    """Esegue un job claimato: completed in caso di successo, error/pending (retry)
    su eccezione secondo MAX_ATTEMPTS."""
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
