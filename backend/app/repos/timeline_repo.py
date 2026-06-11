import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.timeline import TimelineEvent


class TimelineRepository:
    def list_for_user(self, db: Session, user_id: uuid.UUID) -> list[TimelineEvent]:
        stmt = (
            select(TimelineEvent)
            .where(TimelineEvent.user_id == user_id)
            .order_by(desc(TimelineEvent.event_time))
        )
        return list(db.execute(stmt).scalars().all())

    def create(self, db: Session, event: TimelineEvent) -> TimelineEvent:
        db.add(event)
        db.flush()
        db.refresh(event)
        return event


timeline_repository = TimelineRepository()
