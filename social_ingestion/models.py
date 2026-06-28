# GustoPedia/social_ingestion/models.py
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class Platform(str, Enum):
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"


class ScrapeResult(BaseModel):
    media_url: str
    caption: str
    platform: Platform
    mime_type: str  # "video/mp4" or "image/jpeg"
    thumbnail_url: Optional[str] = None


class IngestUrlRequest(BaseModel):
    url: str


class IngestBatchRequest(BaseModel):
    urls: list[str]


class IngestJobResponse(BaseModel):
    job_id: str
    status: JobStatus
    recipe_id: Optional[str] = None
    error: Optional[str] = None
    already_exists: bool = False

