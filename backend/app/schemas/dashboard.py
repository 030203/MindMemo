from datetime import datetime

from pydantic import BaseModel, Field


class DashboardOverview(BaseModel):
    today_focus: str
    today_todos: int
    overdue_todos: int
    recent_memories: int
    pending_reviews: int
    daily_summary: str


class ReminderItem(BaseModel):
    type: str
    level: str
    title: str
    message: str
    todo_id: str
    due_at: datetime | None = None


class InsightSourceItem(BaseModel):
    type: str
    id: str
    title: str
    snippet: str
    event_time: datetime | None = None


class MemoryInsightCard(BaseModel):
    kind: str
    title: str
    value: str
    detail: str
    tone: str
    items: list[str]
    question: str
    sources: list[InsightSourceItem] = Field(default_factory=list)


class DashboardInsights(BaseModel):
    cards: list[MemoryInsightCard]
