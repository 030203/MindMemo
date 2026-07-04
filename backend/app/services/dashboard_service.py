import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.repos.memory_repo import memory_repository
from app.repos.reminder_repo import reminder_repository
from app.repos.review_repo import review_repository
from app.repos.todo_repo import todo_repository
from app.schemas.dashboard import DashboardOverview, ReminderItem
from app.services.reminder_service import reminder_service


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class DashboardService:
    def get_overview(self, db: Session, user_id: uuid.UUID) -> DashboardOverview:
        todos = todo_repository.list_for_user(db, user_id, exclude_reminders=True)
        active_todos = [todo for todo in todos if todo.status != "done"]
        now = utcnow()
        overdue_todos = [
            todo
            for todo in active_todos
            if ensure_utc(todo.due_at) is not None and ensure_utc(todo.due_at) < now
        ]
        recent_memories = memory_repository.count_recent(db, user_id, utcnow() - timedelta(days=7))
        pending_reviews = len([item for item in review_repository.list_for_user(db, user_id) if item.status == "pending"])

        focus_titles = [todo.title for todo in active_todos[:2]]
        today_focus = "，".join(focus_titles) if focus_titles else "今天暂时没有高优先级任务，适合整理记录和回顾进展。"

        return DashboardOverview(
            today_focus=today_focus,
            today_todos=len(active_todos),
            overdue_todos=len(overdue_todos),
            recent_memories=recent_memories,
            pending_reviews=pending_reviews,
            daily_summary="系统会周期性扫描待办，持续生成提醒状态，并优先关注逾期、临近截止和高优先级事项。",
        )

    def list_reminders(self, db: Session, user_id: uuid.UUID, limit: int = 5) -> list[ReminderItem]:
        reminder_service.sync_user_reminders(db, user_id)
        reminders = reminder_repository.list_for_user(db, user_id, active_only=True)[:limit]
        return [
            ReminderItem(
                id=str(item.id),
                type=item.reminder_type,
                level=item.level,
                title=item.title,
                message=item.message,
                todo_id=str(item.todo_id),
                due_at=ensure_utc(item.due_at),
            )
            for item in reminders
        ]


dashboard_service = DashboardService()
