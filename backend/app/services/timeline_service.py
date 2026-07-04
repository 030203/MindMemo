import uuid

from sqlalchemy.orm import Session

from app.repos.timeline_repo import timeline_repository
from app.schemas.timeline import TimelineEventResponse


class TimelineService:
    def list_timeline(self, db: Session, user_id: uuid.UUID) -> list[TimelineEventResponse]:
        events = timeline_repository.list_for_user(db, user_id)
        return [
            TimelineEventResponse(
                id=str(event.id),
                title=event.title,
                summary=event.summary or "",
                event_type=event.event_type,
                event_time=event.event_time,
            )
            for event in events
        ]


timeline_service = TimelineService()
