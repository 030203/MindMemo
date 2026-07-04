"""
Goal 模型 - 用户长期目标和项目

Phase 1 新增: 分层记忆重构
- Goal: 用户的目标/项目实体
- MemoryGoalLink: 记忆与目标的多对多关联

设计原则:
- 目标有生命周期: active -> paused -> completed
- 优先级使用整数，数字越大优先级越高
- 通过 MemoryGoalLink 关联记忆，支持相关性评分
"""
import uuid

from sqlalchemy import ForeignKey, Float, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Goal(Base, TimestampMixin):
    """
    用户目标 - 长期追踪对象

    使用场景:
    - 用户设定"完成项目A"，后续记忆可关联到此目标
    - Agent 可查询活跃目标来提供更相关的回答

    关联:
    - user: 所属用户 (User.goals)
    - memory_links: 关联的记忆 (MemoryGoalLink.goal)
    """

    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # 越大越优先
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)  # active / paused / completed

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="goals")
    memory_links: Mapped[list["MemoryGoalLink"]] = relationship(
        "MemoryGoalLink", back_populates="goal", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Goal {self.title!r} [{self.status}]>"


class MemoryGoalLink(Base, TimestampMixin):
    """
    记忆-目标关联表 - 多对多关系

    使用场景:
    - 将一段记忆关联到某个目标
    - 通过相关性评分 (relevance_score) 量化关联强度
    - 唯一约束: 同一记忆和目标只能关联一次

    索引:
    - idx_memory_goal_links_memory: 按记忆ID查询关联的目标
    - idx_memory_goal_links_goal: 按目标ID查询关联的记忆
    """

    __tablename__ = "memory_goal_links"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    memory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("memory_items.id", ondelete="CASCADE"), nullable=False
    )
    goal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("goals.id", ondelete="CASCADE"), nullable=False
    )
    relevance_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    # 关系
    memory: Mapped["MemoryItem"] = relationship("MemoryItem", back_populates="goal_links")
    goal: Mapped["Goal"] = relationship("Goal", back_populates="memory_links")

    # 表级约束和索引
    __table_args__ = (
        UniqueConstraint("memory_id", "goal_id", name="uq_memory_goal"),
        Index("idx_memory_goal_links_memory", "memory_id"),
        Index("idx_memory_goal_links_goal", "goal_id"),
    )

    def __repr__(self) -> str:
        return f"<MemoryGoalLink memory={self.memory_id} goal={self.goal_id}>"
