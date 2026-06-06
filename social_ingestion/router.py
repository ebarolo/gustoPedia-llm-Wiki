import logging

from fastapi import APIRouter, Depends, HTTPException

from shared.auth import require_auth
from shared.supabase import get_supabase_client
from social_ingestion.models import IngestBatchRequest, IngestJobResponse, IngestUrlRequest
from social_ingestion.service import SocialIngestionService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/social", tags=["social-ingestion"])


def _get_service() -> SocialIngestionService:
    return SocialIngestionService(db=get_supabase_client())


@router.post("/ingest", dependencies=[Depends(require_auth)], response_model=IngestJobResponse)
async def ingest_url(body: IngestUrlRequest):
    svc = _get_service()
    return await svc.ingest_url(body.url)


@router.post("/ingest-batch", dependencies=[Depends(require_auth)], response_model=list[IngestJobResponse])
async def ingest_batch(body: IngestBatchRequest):
    if not body.urls:
        raise HTTPException(status_code=400, detail="urls must not be empty")
    if len(body.urls) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 URLs per batch")
    svc = _get_service()
    return await svc.ingest_batch(body.urls)
