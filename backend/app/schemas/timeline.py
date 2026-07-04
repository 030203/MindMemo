from datetime import datetime

from pydantic import BaseModel


class TimelineEventResponse(BaseModel):
    id: str
    title: str
    summary: str
    event_type: str
    event_time: datetime
