"""
Insight 模型 - 洞察缓存

Phase 1 新增: 分层记忆重构
- Insight: 存储派生的分析结果（模式、聚类、报告）
- 隔离派生数据与原始记忆，防止洞察污染检索

设计原则:
- 只读缓存: 不参与原始记忆检索
- 有过期机制: expires_at 支持自动清理
- 结构化数据: data 字段 (JSONB) 存储可查询的分析结果
- 置信度评分: confidence_score 标记洞察质量
"""
import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.types import JSON_VARIANT


class Insight(Base, TimestampMixin):
    """
    洞察缓存 - 派生的分析结果

    使用场景:
    - Insight Agent 生成的行为模式分析
    - 消费/学习/项目等维度的定期报告
    - LLM 生成的聚类摘要

    与 MemoryItem 的关系:
    - Insight 是派生数据，MemoryItem 是原始数据
    - Insight 不参与记忆检索，仅用于展示和分析
    - Insight 可过期，MemoryItem 持久保存

    索引:
    - idx_insights_user_type: 按用户+类型快速过滤
    - idx_insights_created: 按创建时间排序
    """

    __tablename__ = "insights"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    insight_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # pattern / cluster / report / expense / reflection / learning / project
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON_VARIANT, nullable=True)  # 结构化洞察数据
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)  # 可选的过期时间

    # 关系
    user: Mapped["User"] = relationship("User", back_populates="insights")

    def __repr__(self) -> str:
        return f"<Insight {self.title!r} [{self.insight_type}] confidence={self.confidence_score}>"
