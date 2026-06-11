from datetime import datetime
import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.reminder import ReminderEvent


class ReminderRepository:
    def list_for_user(self, db: Session, user_id: uuid.UUID, *, active_only: bool = True) -> list[ReminderEvent]:
        stmt = select(ReminderEvent).where(ReminderEvent.user_id == user_id)
        if active_only:
            stmt = stmt.where(ReminderEvent.status == "active")
        stmt = stmt.order_by(desc(ReminderEvent.created_at))
        return list(db.execute(stmt).scalars().all())

    def list_for_todo(self, db: Session, todo_id: uuid.UUID) -> list[ReminderEvent]:
        stmt = (
            select(ReminderEvent)
            .where(ReminderEvent.todo_id == todo_id)
            .order_by(desc(ReminderEvent.created_at))
        )
        return list(db.execute(stmt).scalars().all())

    def list_pending_delivery(self, db: Session, limit: int = 20) -> list[ReminderEvent]:
        stmt = (
            select(ReminderEvent)
            .where(ReminderEvent.status == "active", ReminderEvent.sent_at.is_(None))
            .order_by(desc(ReminderEvent.created_at))
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())

    def create(self, db: Session, reminder: ReminderEvent) -> ReminderEvent:
        db.add(reminder)
        db.flush()
        db.refresh(reminder)
        return reminder

    def mark_sent(self, db: Session, reminder: ReminderEvent, sent_at: datetime) -> ReminderEvent:
        reminder.sent_at = sent_at
        db.flush()
        return reminder


reminder_repository = ReminderRepository()
