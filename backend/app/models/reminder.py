import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.types import JSON_VARIANT


class ReminderEvent(Base, TimestampMixin):
    __tablename__ = "reminder_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    todo_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("todos.id"), index=True, nullable=False)
    reminder_type: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(nullable=True)
    meta_payload: Mapped[dict] = mapped_column("metadata", JSON_VARIANT, default=dict, nullable=False)
