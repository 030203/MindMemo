from datetime import datetime

from pydantic import BaseModel


class DashboardOverview(BaseModel):
    today_focus: str
    today_todos: int
    overdue_todos: int
    recent_memories: int
    pending_reviews: int
    daily_summary: str


class ReminderItem(BaseModel):
    id: str
    type: str
    level: str
    title: str
    message: str
    todo_id: str
    due_at: datetime | None = None
