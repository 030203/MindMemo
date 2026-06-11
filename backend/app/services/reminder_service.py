from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy.orm import Session

from app.models.reminder import ReminderEvent
from app.models.timeline import TimelineEvent
from app.models.todo import TodoItem
from app.repos.reminder_repo import reminder_repository
from app.repos.timeline_repo import timeline_repository
from app.repos.todo_repo import todo_repository


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def localnow() -> datetime:
    return datetime.now()


def ensure_local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone().replace(tzinfo=None)


class ReminderService:
    def sync_user_reminders(self, db: Session, user_id: uuid.UUID) -> int:
        todos = todo_repository.list_for_user(db, user_id, sort="priority")
        created = 0
        now = localnow()

        for todo in todos:
            if todo.status == "done":
                created += self._archive_existing_for_todo(db, todo)
                continue

            reminder_payload = self._build_reminder_payload(todo, now)
            if reminder_payload is None:
                created += self._archive_existing_for_todo(db, todo)
                continue

            existing = reminder_repository.list_for_todo(db, todo.id)
            matching = next(
                (
                    item
                    for item in existing
                    if item.status == "active"
                    and item.reminder_type == reminder_payload["reminder_type"]
                    and item.level == reminder_payload["level"]
                    and item.title == reminder_payload["title"]
                    and item.message == reminder_payload["message"]
                ),
                None,
            )
            if matching is not None:
                for item in existing:
                    if item.id != matching.id and item.status == "active":
                        item.status = "dismissed"
                continue

            for item in existing:
                if item.status == "active":
                    item.status = "dismissed"

            reminder = ReminderEvent(
                user_id=todo.user_id,
                todo_id=todo.id,
                reminder_type=reminder_payload["reminder_type"],
                level=reminder_payload["level"],
                title=reminder_payload["title"],
                message=reminder_payload["message"],
                due_at=todo.due_at,
                status="active",
                meta_payload={"source": "scheduler"},
            )
            reminder_repository.create(db, reminder)
            timeline_repository.create(
                db,
                TimelineEvent(
                    user_id=todo.user_id,
                    event_type="reminder_created",
                    ref_type="todo",
                    ref_id=todo.id,
                    title=f"Reminder created: {todo.title}",
                    summary=reminder.message,
                    event_time=now,
                    meta_payload={"reminder_type": reminder.reminder_type, "level": reminder.level},
                ),
            )
            created += 1

        if created > 0:
            db.commit()
        else:
            db.flush()
        return created

    def list_reminders(self, db: Session, user_id: uuid.UUID, limit: int = 5) -> list[ReminderEvent]:
        reminders = reminder_repository.list_for_user(db, user_id, active_only=True)
        return reminders[:limit]

    def sync_all_users(self, db: Session) -> int:
        todos = todo_repository.list_all_active(db)
        user_ids = list(dict.fromkeys(todo.user_id for todo in todos))
        total_created = 0
        for user_id in user_ids:
            total_created += self.sync_user_reminders(db, user_id)
        return total_created

    def _archive_existing_for_todo(self, db: Session, todo: TodoItem) -> int:
        changed = 0
        for item in reminder_repository.list_for_todo(db, todo.id):
            if item.status == "active":
                item.status = "dismissed"
                changed += 1
        return changed

    def _build_reminder_payload(self, todo: TodoItem, now: datetime) -> dict | None:
        due_at = ensure_local(todo.due_at)
        if due_at is not None and due_at < now:
            return {
                "reminder_type": "overdue",
                "level": "high",
                "title": todo.title,
                "message": "This todo is overdue. It is worth handling soon.",
            }
        if due_at is not None and due_at <= now + timedelta(hours=24):
            return {
                "reminder_type": "due_soon",
                "level": "medium",
                "title": todo.title,
                "message": "This todo is due within 24 hours.",
            }
        if todo.priority == "urgent":
            return {
                "reminder_type": "urgent",
                "level": "high",
                "title": todo.title,
                "message": "This todo is marked urgent.",
            }
        if todo.priority == "high" or todo.risk_level == "high":
            return {
                "reminder_type": "important",
                "level": "medium",
                "title": todo.title,
                "message": "This todo is important and should stay visible.",
            }
        if todo.status == "blocked":
            return {
                "reminder_type": "blocked",
                "level": "low",
                "title": todo.title,
                "message": "This todo is blocked. A note or a smaller next step may help.",
            }
        return None


reminder_service = ReminderService()
