# gnammyWiki/wiki/router.py
import asyncio
import logging

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from shared.auth import require_auth
from shared.supabase import get_supabase_client
from wiki import job_manager, worker
from wiki.search import search_wiki_pages
from wiki.models import (
    BackfillRequest,
    ProcessQueueResponse,
    WikiJobResponse,
    WikiJobStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wiki", tags=["wiki"], dependencies=[Depends(require_auth)])


@router.post("/process-queue", response_model=ProcessQueueResponse)
async def process_queue() -> ProcessQueueResponse:
    """Kick del worker: avvia il drain della coda in background e ritorna subito."""
    db = get_supabase_client()
    pending = job_manager.count_pending(db)
    asyncio.create_task(worker.drain(db))
    return ProcessQueueResponse(status="kicked", pending=pending)


@router.post("/backfill", response_model=ProcessQueueResponse)
async def backfill(payload: BackfillRequest) -> ProcessQueueResponse:
    """Accoda job wiki per un sottoinsieme di ricette (o ids espliciti)."""
    db = get_supabase_client()

    if payload.recipe_ids:
        recipe_ids = payload.recipe_ids
    else:
        query = db.table("recipes").select("id").order("created_at", desc=True)
        if payload.limit:
            query = query.limit(payload.limit)
        resp = query.execute()
        recipe_ids = [r["id"] for r in (resp.data or [])]

    enqueued = 0
    for recipe_id in recipe_ids:
        if job_manager.enqueue(db, recipe_id):
            enqueued += 1
    logger.info("Backfill wiki: %d job accodati su %d ricette", enqueued, len(recipe_ids))

    asyncio.create_task(worker.drain(db))
    return ProcessQueueResponse(status="backfill-started", pending=job_manager.count_pending(db))


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1),
    top_k: int = Query(5, ge=1, le=20),
    page_types: Optional[str] = Query(None, description="Tipi pagina separati da virgola"),
) -> dict:
    """Ricerca ibrida sulla wiki, per QA manuale e dashboard."""
    db = get_supabase_client()
    types_list = [t.strip() for t in page_types.split(",") if t.strip()] if page_types else None
    rows = search_wiki_pages(db, q, top_k=top_k, page_types=types_list)
    return {"query": q, "results": rows}


@router.get("/jobs/{job_id}", response_model=WikiJobResponse)
async def get_job(job_id: str) -> WikiJobResponse:
    db = get_supabase_client()
    job = job_manager.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job non trovato")
    return WikiJobResponse(
        job_id=job["id"],
        status=WikiJobStatus(job["status"]),
        recipe_id=job["recipe_id"],
        attempts=job.get("attempts", 0),
        pages_touched=job.get("pages_touched") or [],
        error=job.get("error_message"),
    )
