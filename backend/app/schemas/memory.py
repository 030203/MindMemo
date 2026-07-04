from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class MemoryCreateRequest(BaseModel):
    title: str
    content: str
    category: str = "memo"
    source_type: str = "memo"
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


class TextIngestRequest(BaseModel):
    content: str
    title: str | None = None
    record_type: str = "memo"              # "memo" | "todo" | "reminder"
    due_at: datetime | None = None
    remind_at: datetime | None = None

    @model_validator(mode="after")
    def validate_reminder_has_time(self):
        if self.record_type == "reminder" and self.remind_at is None:
            raise ValueError("reminder 类型必须提供 remind_at")
        return self


class TextIngestResult(BaseModel):
    memory_id: str
    todo_id: str | None = None
    record_type: str


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


class MemoryDetail(MemoryListItem):
    content_raw: str
    keywords: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
