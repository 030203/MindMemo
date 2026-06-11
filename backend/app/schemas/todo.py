from datetime import datetime

from pydantic import BaseModel


class TodoCreateRequest(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    due_at: datetime | None = None
    source_memory_id: str | None = None


class TodoUpdateRequest(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    status: str = "pending"
    due_at: datetime | None = None
    source_memory_id: str | None = None


class TodoResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    priority: str
    due_at: datetime | None = None
    risk_level: str
    source_memory_id: str | None = None
