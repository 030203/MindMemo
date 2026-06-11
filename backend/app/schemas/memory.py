from datetime import datetime

from pydantic import BaseModel, Field


class MemoryCreateRequest(BaseModel):
    title: str
    content: str
    category: str = "memo"
    source_type: str = "memo"
    run_ai_parse: bool = True
    source_url: str | None = None
    file_name: str | None = None
    source_mime_type: str | None = None


class MemoryUpdateRequest(BaseModel):
    title: str
    content: str
    category: str = "memo"


class UrlIngestRequest(BaseModel):
    url: str
    title: str | None = None
    category: str = "learning"


class MemoryListItem(BaseModel):
    id: str
    title: str
    source_type: str
    source_url: str | None = None
    file_name: str | None = None
    content_summary: str
    category: str
    tags: list[str] = Field(default_factory=list)
    importance_score: float
    event_time: datetime | None = None
    due_time: datetime | None = None
    status: str


class ExtractedFactResponse(BaseModel):
    id: str
    fact_type: str
    title: str
    structured_payload: dict = Field(default_factory=dict)
    confidence_score: float
    event_time: datetime | None = None
    source: str


class MemoryRelatedItem(BaseModel):
    id: str
    title: str
    content_summary: str
    category: str
    relation_type: str
    relation_reason: str
    score: float
    event_time: datetime | None = None


class MemoryDetail(MemoryListItem):
    content_raw: str
    keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    extracted_facts: list[ExtractedFactResponse] = Field(default_factory=list)
