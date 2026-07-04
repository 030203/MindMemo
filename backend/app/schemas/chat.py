from datetime import datetime

from pydantic import BaseModel


class ChatSessionCreateRequest(BaseModel):
    context_type: str = "global"
    context_id: str | None = None
    title: str | None = None


class ChatSessionResponse(BaseModel):
    session_id: str
    context_type: str
    context_id: str | None
    title: str | None
    created_at: datetime
    pinned: bool = False


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime


class SessionUpdateRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None


class SessionQARequest(BaseModel):
    question: str


class SessionQAResponse(BaseModel):
    answer: str
    session_id: str
    message_id: str
