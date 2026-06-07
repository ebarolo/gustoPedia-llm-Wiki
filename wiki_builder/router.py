# gnammyAssistant/wiki_builder/router.py
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel

from shared.auth import require_auth
from shared.supabase import get_supabase_client
from wiki_builder.wiki_service import WikiService
from wiki_builder.pdf_ingestion_service import PDFIngestionService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/wiki", tags=["wiki"])

_wiki_service: Optional[WikiService] = None


def _get_wiki_service() -> WikiService:
    global _wiki_service
    if _wiki_service is None:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        if not gemini_key:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
        _wiki_service = WikiService(supabase_client=get_supabase_client(), gemini_api_key=gemini_key)
    return _wiki_service


class IngestRecipeRequest(BaseModel):
    recipe_id: str


class JobRecord(BaseModel):
    id: str
    file_path: str
    url: Optional[str] = None
    parent_job_id: Optional[str] = None


class IngestRecipePDFRequest(BaseModel):
    record: JobRecord


class IngestBookPDFRequest(BaseModel):
    record: JobRecord


class IngestBookChapterRequest(BaseModel):
    record: JobRecord


class BackfillRequest(BaseModel):
    limit: int = 50
    offset: int = 0


# Background task helpers
async def _run_recipe_pdf(svc: PDFIngestionService, job_id: str, file_path: str):
    try:
        await svc.process_recipe_pdf(job_id, file_path)
    except Exception as e:
        logger.exception("Background process_recipe_pdf failed for job_id=%s", job_id)


async def _run_book_pdf(svc: PDFIngestionService, job_id: str, file_path: str):
    try:
        await svc.process_book_pdf(job_id, file_path)
    except Exception as e:
        logger.exception("Background process_book_pdf failed for job_id=%s", job_id)


async def _run_book_chapter(svc: PDFIngestionService, job_id: str, parent_job_id: str, chapter_index: int, file_path: str):
    try:
        await svc.process_book_chapter(job_id, parent_job_id, chapter_index, file_path)
    except Exception as e:
        logger.exception("Background process_book_chapter failed for job_id=%s", job_id)


@router.post("/ingest-recipe-pdf", dependencies=[Depends(require_auth)])
async def ingest_recipe_pdf(body: IngestRecipePDFRequest, background_tasks: BackgroundTasks):
    svc = PDFIngestionService(db=get_supabase_client())
    background_tasks.add_task(_run_recipe_pdf, svc, body.record.id, body.record.file_path)
    return {"status": "accepted", "message": "Single recipe PDF ingestion job queued"}


@router.post("/ingest-book-pdf", dependencies=[Depends(require_auth)])
async def ingest_book_pdf(body: IngestBookPDFRequest, background_tasks: BackgroundTasks):
    svc = PDFIngestionService(db=get_supabase_client())
    background_tasks.add_task(_run_book_pdf, svc, body.record.id, body.record.file_path)
    return {"status": "accepted", "message": "Cookbook PDF ingestion job queued"}


@router.post("/ingest-book-chapter", dependencies=[Depends(require_auth)])
async def ingest_book_chapter(body: IngestBookChapterRequest, background_tasks: BackgroundTasks):
    svc = PDFIngestionService(db=get_supabase_client())
    
    # Parse chapter index from URL: pdf-book-chapter://<parent_id>/<chapter_index>
    try:
        url_parts = body.record.url.replace("pdf-book-chapter://", "").split("/")
        parent_job_id = url_parts[0]
        chapter_index = int(url_parts[1])
    except Exception as e:
        logger.exception("Failed to parse chapter_index from url=%s", body.record.url)
        raise HTTPException(status_code=400, detail=f"Invalid job URL format: {body.record.url}")
        
    background_tasks.add_task(_run_book_chapter, svc, body.record.id, parent_job_id, chapter_index, body.record.file_path)
    return {"status": "accepted", "message": "Book chapter PDF ingestion job queued"}


@router.post("/ingest-recipe", dependencies=[Depends(require_auth)])
async def ingest_recipe(body: IngestRecipeRequest):
    svc = _get_wiki_service()
    result = svc.ingest_recipe(body.recipe_id)
    if not result["ok"]:
        raise HTTPException(status_code=422, detail=result.get("error"))
    return result


@router.post("/backfill", dependencies=[Depends(require_auth)])
async def backfill(body: BackfillRequest):
    svc = _get_wiki_service()
    try:
        return svc.backfill(limit=body.limit, offset=body.offset)
    except Exception:
        logger.exception("Backfill failed")
        raise HTTPException(status_code=500, detail="Backfill failed")


@router.post("/trigger-daily-digest", dependencies=[Depends(require_auth)])
async def trigger_daily_digest():
    svc = _get_wiki_service()
    try:
        success = svc.trigger_daily_digest()
        return {"ok": success}
    except Exception:
        logger.exception("Daily digest trigger failed")
        raise HTTPException(status_code=500, detail="Daily digest trigger failed")



@router.get("/entities")
async def list_entities(
    q: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
):
    try:
        db = get_supabase_client()
        query = db.table("wiki_entities").select(
            "id,slug,name,type,aliases,summary,related_entity_slugs,related_concept_slugs,source_recipe_ids,version,updated_at"
        )
        if type:
            query = query.eq("type", type)
        if q:
            query = query.ilike("name", f"%{q}%")
        resp = query.limit(limit).execute()
        return {"items": resp.data or [], "count": len(resp.data or [])}
    except Exception:
        logger.exception("Failed to list entities")
        raise HTTPException(status_code=500, detail="Failed to fetch entities")


@router.get("/concepts")
async def list_concepts(
    q: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
):
    try:
        db = get_supabase_client()
        query = db.table("wiki_concepts").select(
            "id,slug,name,type,aliases,definition,key_characteristics,applications,related_concept_slugs,related_entity_slugs,source_recipe_ids,version,updated_at"
        )
        if type:
            query = query.eq("type", type)
        if q:
            query = query.ilike("name", f"%{q}%")
        resp = query.limit(limit).execute()
        return {"items": resp.data or [], "count": len(resp.data or [])}
    except Exception:
        logger.exception("Failed to list concepts")
        raise HTTPException(status_code=500, detail="Failed to fetch concepts")


@router.get("/status")
async def ingestion_status():
    try:
        db = get_supabase_client()
        resp = db.table("wiki_ingestion_log").select("status").execute()
        rows = resp.data or []
        counts: dict[str, int] = {}
        for row in rows:
            s = row["status"]
            counts[s] = counts.get(s, 0) + 1
        total_entities = db.table("wiki_entities").select("id", count="exact").execute().count or 0
        total_concepts = db.table("wiki_concepts").select("id", count="exact").execute().count or 0
        return {"log_counts": counts, "total_entities": total_entities, "total_concepts": total_concepts}
    except Exception:
        logger.exception("Failed to get wiki status")
        raise HTTPException(status_code=500, detail="Failed to get status")
