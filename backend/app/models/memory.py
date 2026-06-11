import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.types import EMBEDDING_VARIANT, JSON_VARIANT


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
    confidence_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    is_todo_candidate: Mapped[bool] = mapped_column(default=False, nullable=False)
    event_time: Mapped[datetime | None] = mapped_column(nullable=True)
    due_time: Mapped[datetime | None] = mapped_column(nullable=True)
    last_recalled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_by: Mapped[str] = mapped_column(String(20), default="user", nullable=False)


class MemoryChunk(Base, TimestampMixin):
    __tablename__ = "memory_chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    memory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("memory_items.id"), index=True, nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(EMBEDDING_VARIANT, nullable=True)
    token_count: Mapped[int | None] = mapped_column(nullable=True)
    keywords: Mapped[list] = mapped_column(JSON_VARIANT, default=list, nullable=False)
    meta_payload: Mapped[dict] = mapped_column("metadata", JSON_VARIANT, default=dict, nullable=False)


class MemoryRelation(Base, TimestampMixin):
    __tablename__ = "memory_relations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    from_memory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("memory_items.id"), nullable=False
    )
    to_memory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("memory_items.id"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    relation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    created_by: Mapped[str] = mapped_column(String(20), default="agent", nullable=False)


class ExtractedFact(Base, TimestampMixin):
    __tablename__ = "extracted_facts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    memory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("memory_items.id"), index=True, nullable=False
    )
    fact_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    structured_payload: Mapped[dict] = mapped_column(JSON_VARIANT, default=dict, nullable=False)
    confidence_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    event_time: Mapped[datetime | None] = mapped_column(nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="rule_v1", nullable=False)
