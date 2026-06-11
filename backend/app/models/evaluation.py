import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.types import JSON_VARIANT


class RetrievalTrace(Base, TimestampMixin):
    __tablename__ = "retrieval_traces"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), default="memory_only", nullable=False)
    retrieval_strategy: Mapped[str] = mapped_column(String(64), default="chunk_v1", nullable=False)
    answer_source: Mapped[str] = mapped_column(String(64), default="memory_rag", nullable=False)
    candidates: Mapped[list] = mapped_column(JSON_VARIANT, default=list, nullable=False)
    selected_citations: Mapped[list] = mapped_column(JSON_VARIANT, default=list, nullable=False)
    meta_payload: Mapped[dict] = mapped_column("metadata", JSON_VARIANT, default=dict, nullable=False)


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    retrieval_trace_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("retrieval_traces.id"),
        index=True,
        nullable=True,
    )
    run_type: Mapped[str] = mapped_column(String(64), default="qa_agentic_rag", nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), default="memory_only", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="completed", nullable=False)
    answer_source: Mapped[str] = mapped_column(String(64), default="memory_rag", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_payload: Mapped[dict] = mapped_column("metadata", JSON_VARIANT, default=dict, nullable=False)


class AgentRunStep(Base, TimestampMixin):
    __tablename__ = "agent_run_steps"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), index=True, nullable=False)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agent_runs.id"), index=True, nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="done", nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metric: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_payload: Mapped[dict] = mapped_column("metadata", JSON_VARIANT, default=dict, nullable=False)
