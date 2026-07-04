"""
InsightRepository - 洞察数据访问层

Phase 1 新增: 分层记忆重构

核心职责:
1. 洞察的 CRUD 操作
2. 按时间/类型查询
3. 过期清理

设计原则:
- 洞察是派生数据，不参与原始记忆检索
- 支持过期机制，自动清理旧数据
- 按用户隔离
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.insight import Insight


class InsightRepository:
    """洞察仓库 - 管理派生的分析结果"""

    def create(
        self,
        db: Session,
        user_id: uuid.UUID,
        insight_type: str,
        title: str,
        content: str,
        data: dict | None = None,
        confidence_score: float = 0.0,
        expires_at: datetime | None = None,
    ) -> Insight:
        """
        创建新洞察

        Args:
            db: 数据库会话
            user_id: 用户ID
            insight_type: 洞察类型 (pattern / cluster / report / expense / reflection / learning / project)
            title: 洞察标题
            content: 洞察内容 (markdown 文本)
            data: 结构化数据 (JSONB, 可选)
            confidence_score: 置信度评分 (0.0 ~ 1.0)
            expires_at: 过期时间 (可选)

        Returns:
            新创建的 Insight 实例
        """
        insight = Insight(
            user_id=user_id,
            insight_type=insight_type,
            title=title,
            content=content,
            data=data,
            confidence_score=confidence_score,
            expires_at=expires_at,
        )
        db.add(insight)
        db.commit()
        db.refresh(insight)
        return insight

    def get_recent(
        self, db: Session, user_id: uuid.UUID, days: int = 7, limit: int = 10
    ) -> list[Insight]:
        """
        获取最近 N 天的洞察

        Args:
            db: 数据库会话
            user_id: 用户ID
            days: 时间范围 (天)
            limit: 返回数量上限

        Returns:
            洞察列表 (按创建时间倒序)
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return (
            db.query(Insight)
            .filter(
                Insight.user_id == user_id,
                Insight.created_at >= cutoff,
            )
            .order_by(desc(Insight.created_at))
            .limit(limit)
            .all()
        )

    def get_by_type(
        self,
        db: Session,
        user_id: uuid.UUID,
        insight_type: str,
        limit: int = 10,
    ) -> list[Insight]:
        """
        按类型获取洞察

        Args:
            db: 数据库会话
            user_id: 用户ID
            insight_type: 洞察类型
            limit: 返回数量上限

        Returns:
            洞察列表 (按创建时间倒序)
        """
        return (
            db.query(Insight)
            .filter(
                Insight.user_id == user_id,
                Insight.insight_type == insight_type,
            )
            .order_by(desc(Insight.created_at))
            .limit(limit)
            .all()
        )

    def get_by_id(
        self, db: Session, insight_id: uuid.UUID, user_id: uuid.UUID
    ) -> Insight | None:
        """
        根据 ID 获取洞察 (用户隔离)

        Args:
            db: 数据库会话
            insight_id: 洞察ID
            user_id: 用户ID

        Returns:
            Insight 实例，未找到返回 None
        """
        return (
            db.query(Insight)
            .filter(Insight.id == insight_id, Insight.user_id == user_id)
            .first()
        )

    def delete_expired(self, db: Session) -> int:
        """
        删除所有已过期的洞察 (全局清理，不限定用户)

        Returns:
            删除的记录数
        """
        now = datetime.now(timezone.utc)
        deleted = (
            db.query(Insight)
            .filter(
                Insight.expires_at.isnot(None),
                Insight.expires_at < now,
            )
            .delete()
        )
        db.commit()
        return deleted

    def delete_for_user(
        self, db: Session, user_id: uuid.UUID, insight_id: uuid.UUID
    ) -> bool:
        """
        删除用户的某个洞察

        Args:
            db: 数据库会话
            user_id: 用户ID
            insight_id: 洞察ID

        Returns:
            True 表示成功删除，False 表示未找到
        """
        insight = self.get_by_id(db, insight_id, user_id)
        if insight is None:
            return False
        db.delete(insight)
        db.commit()
        return True


# 全局单例 (遵循项目约定)
insight_repository = InsightRepository()
