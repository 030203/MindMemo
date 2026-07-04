"""
AgentRun model - 保存 Agent 执行轨迹

用于记录每次 Agent 执行过程中的完整推理链路（trajectory），
包括 thought 和 action 两步，供调试和可视化查看。
"""
import uuid
from datetime import datetime

from sqlalchemy import String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.types import JSON_VARIANT


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    trajectory: Mapped[list | None] = mapped_column(JSON_VARIANT, nullable=True)
    tool_calls: Mapped[list | None] = mapped_column(JSON_VARIANT, nullable=True)
    run_metadata: Mapped[dict | None] = mapped_column(JSON_VARIANT, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="success", nullable=False)
