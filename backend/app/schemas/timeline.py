from datetime import datetime

from pydantic import BaseModel


class TimelineEventResponse(BaseModel):
    id: str
    title: str
    summary: str
    event_type: str
    event_time: datetime


class MemorySignalResponse(BaseModel):
    id: str
    memory_id: str
    fact_type: str
    title: str
    summary: str
    event_time: datetime
    confidence_score: float
    tone: str
    metadata: dict
