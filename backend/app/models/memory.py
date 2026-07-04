import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.types import JSON_VARIANT


class MemoryItem(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "memory_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_raw: Mapped[str] = mapped_column(Text, nullable=False)
    content_clean: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    tags: Mapped[list] = mapped_column(JSON_VARIANT, default=list, nullable=False)
    keywords: Mapped[list] = mapped_column(JSON_VARIANT, default=list, nullable=False)
    entities: Mapped[list] = mapped_column(JSON_VARIANT, default=list, nullable=False)
    time_info: Mapped[dict] = mapped_column(JSON_VARIANT, default=dict, nullable=False)
    importance_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    # DB still has this column; kept for compatibility, no longer used in app logic
    confidence_score: Mapped[float] = mapped_column("confidence_score", default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    is_todo_candidate: Mapped[bool] = mapped_column(default=False, nullable=False)
    event_time: Mapped[datetime | None] = mapped_column(nullable=True)
    due_time: Mapped[datetime | None] = mapped_column(nullable=True)
    last_recalled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_by: Mapped[str] = mapped_column(String(20), default="user", nullable=False)

    # Phase 1: 目标关联
    goal_links: Mapped[list["MemoryGoalLink"]] = relationship(
        "MemoryGoalLink", back_populates="memory", cascade="all, delete-orphan"
    )
