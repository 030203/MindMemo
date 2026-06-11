import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.types import JSON_VARIANT


class TodoItem(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "todos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    source_memory_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("memory_items.id"), nullable=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("todos.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    priority: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(nullable=True)
    remind_at: Mapped[datetime | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    risk_level: Mapped[str] = mapped_column(String(16), default="none", nullable=False)
    ai_generated: Mapped[bool] = mapped_column(default=False, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(default=False, nullable=False)
    meta_payload: Mapped[dict] = mapped_column("metadata", JSON_VARIANT, default=dict, nullable=False)
