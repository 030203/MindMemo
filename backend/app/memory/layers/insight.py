"""
Insight Cache - 洞察缓存层

核心职责:
1. 存储派生的洞察数据 (模式、聚类、报告)
2. 隔离派生数据与原始记忆
3. 防止洞察污染检索
4. 支持按类型和时间查询

特点:
- 只读缓存: 不参与原始记忆检索
- 有过期机制: expires_at 支持自动清理
- 结构化数据: data 字段存储 JSONB

Phase 1: 调用 insight_repository 实现完整功能
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.repos.insight_repo import insight_repository


class InsightCache:
    """
    洞察缓存 - 派生的分析结果

    使用示例:
        ic = InsightCache(db, user_id)

        # 获取最近的洞察
        insights = ic.get_recent(days=7)

        # 保存新洞察
        ic.save_insight("pattern", "最近一周每天都提到项目A", data={...})
    """

    def __init__(self, db: Session, user_id: uuid.UUID):
        self.db = db
        self.user_id = user_id

    def get_recent(self, days: int = 7, limit: int = 10) -> list[dict]:
        """
        获取最近的洞察

        Args:
            days: 时间范围 (天)
            limit: 返回数量

        Returns:
            洞察列表 (字典格式)
        """
        if self.db is None:
            return []
        insights = insight_repository.get_recent(
            self.db, self.user_id, days=days, limit=limit
        )
        return [
            {
                "id": str(i.id),
                "insight_type": i.insight_type,
                "title": i.title,
                "content": i.content,
                "data": i.data,
                "confidence_score": i.confidence_score,
                "created_at": i.created_at.isoformat() if i.created_at else None,
                "expires_at": i.expires_at.isoformat() if i.expires_at else None,
            }
            for i in insights
        ]

    def get_by_type(
        self, insight_type: str, limit: int = 10
    ) -> list[dict]:
        """
        按类型获取洞察

        Args:
            insight_type: 洞察类型 (pattern/cluster/report/expense/reflection/learning/project)
            limit: 返回数量

        Returns:
            洞察列表
        """
        if self.db is None:
            return []
        insights = insight_repository.get_by_type(
            self.db, self.user_id, insight_type, limit=limit
        )
        return [
            {
                "id": str(i.id),
                "insight_type": i.insight_type,
                "title": i.title,
                "content": i.content,
                "data": i.data,
                "confidence_score": i.confidence_score,
                "created_at": i.created_at.isoformat() if i.created_at else None,
                "expires_at": i.expires_at.isoformat() if i.expires_at else None,
            }
            for i in insights
        ]

    def save_insight(
        self,
        insight_type: str,
        title: str,
        content: str,
        data: dict | None = None,
        confidence_score: float = 0.0,
        expires_in_days: int | None = None,
    ) -> uuid.UUID:
        """
        保存洞察到缓存

        Args:
            insight_type: 洞察类型
            title: 洞察标题
            content: 洞察内容 (markdown 文本)
            data: 结构化数据 (可选)
            confidence_score: 置信度评分 (0.0 ~ 1.0)
            expires_in_days: N 天后过期 (可选)

        Returns:
            新创建的洞察ID
        """
        expires_at = None
        if expires_in_days is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

        insight = insight_repository.create(
            self.db,
            user_id=self.user_id,
            insight_type=insight_type,
            title=title,
            content=content,
            data=data,
            confidence_score=confidence_score,
            expires_at=expires_at,
        )
        return insight.id

    def delete_insight(self, insight_id: uuid.UUID) -> bool:
        """
        删除洞察

        Args:
            insight_id: 洞察ID

        Returns:
            True 表示成功删除
        """
        return insight_repository.delete_for_user(self.db, self.user_id, insight_id)

    def cleanup_expired(self) -> int:
        """
        清理过期洞察 (全局)

        Returns:
            删除的记录数
        """
        return insight_repository.delete_expired(self.db)
