# GustoPedia/wiki/models.py
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

PAGE_TYPES = (
    "ingrediente", "tecnica", "piatto", "regione",
    "concetto", "confronto", "sintesi", "stagionalita",
)


class WikiJobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"


class AnalysisUpdate(BaseModel):
    slug: str
    reason: str = ""


class AnalysisCreate(BaseModel):
    slug: str
    title: str
    page_type: str
    reason: str = ""


class AnalysisResult(BaseModel):
    update: list[AnalysisUpdate] = Field(default_factory=list)
    create: list[AnalysisCreate] = Field(default_factory=list)
    links: list[list[str]] = Field(default_factory=list)

    @property
    def planned_slugs(self) -> set[str]:
        return {u.slug for u in self.update} | {c.slug for c in self.create}

    @property
    def is_empty(self) -> bool:
        return not self.update and not self.create


class BackfillRequest(BaseModel):
    limit: Optional[int] = None
    recipe_ids: Optional[list[str]] = None


class ProcessQueueResponse(BaseModel):
    status: str
    pending: int
    processed: int = 0


class WikiJobResponse(BaseModel):
    job_id: str
    status: WikiJobStatus
    recipe_id: str
    attempts: int = 0
    pages_touched: list[str] = Field(default_factory=list)
    error: Optional[str] = None
