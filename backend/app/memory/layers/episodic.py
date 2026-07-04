"""
Episodic Memory - 情节记忆层

核心职责:
1. 封装 memory_items 表，提供时间线视图和事件流查询
2. 支持按时间范围检索
3. 提供摘要统计

特点:
- 持久化存储
- 以时间为主轴
- 记录用户的行为和事件

Phase 1: 调用现有 memory_repository 实现真实数据访问
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional


def _ensure_utc_aware(dt: datetime) -> datetime:
    """将 naive datetime (SQLite) 转为 UTC-aware datetime"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


from sqlalchemy.orm import Session

from app.repos.memory_repo import memory_repository


class EpisodicMemory:
    """
    情节记忆 - 用户的事件流和时间线

    使用示例:
        em = EpisodicMemory(db, user_id)

        # 获取最近的记忆
        recent = em.get_recent_memories(days=7, limit=10)

        # 获取每日统计摘要
        summary = em.get_summary(days=30)
    """

    def __init__(self, db: Session, user_id: uuid.UUID):
        self.db = db
        self.user_id = user_id

    def get_recent_memories(self, days: int = 7, limit: int = 10) -> list[dict]:
        """
        获取最近 N 天的记忆

        Args:
            days: 时间范围 (天)
            limit: 返回数量

        Returns:
            记忆列表 (字典格式，供 Agent 使用)
        """
        if self.db is None:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        count = memory_repository.count_recent(self.db, self.user_id, cutoff)

        # 使用 list_for_user 然后手动过滤时间 (保持与现有 API 兼容)
        all_memories = memory_repository.list_for_user(self.db, self.user_id)

        recent = []
        for m in all_memories:
            if _ensure_utc_aware(m.created_at) >= cutoff:
                recent.append(m)
            if len(recent) >= limit:
                break

        return [
            {
                "id": str(m.id),
                "title": m.title or "",
                "summary": m.content_summary or "",
                "category": m.category,
                "tags": m.tags or [],
                "keywords": m.keywords or [],
                "entities": m.entities or [],
                "importance_score": m.importance_score,
                "source_type": m.source_type,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "event_time": m.event_time.isoformat() if m.event_time else None,
            }
            for m in recent
        ]

    def get_summary(self, days: int = 30) -> dict:
        """
        获取时间范围内的摘要统计

        Args:
            days: 时间范围 (天)

        Returns:
            包含统计信息和最近动态的字典
        """
        if self.db is None:
            return {"total_memories": 0, "date_range": f"最近{days}天", "most_active_day": None}
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        count = memory_repository.count_recent(self.db, self.user_id, cutoff)

        # 按类别统计
        all_memories = memory_repository.list_for_user(self.db, self.user_id)
        category_counts: dict[str, int] = {}
        for m in all_memories:
            if _ensure_utc_aware(m.created_at) >= cutoff:
                cat = m.category or "other"
                category_counts[cat] = category_counts.get(cat, 0) + 1

        # 找出最活跃的日期
        daily_counts: dict[str, int] = {}
        for m in all_memories:
            if _ensure_utc_aware(m.created_at) >= cutoff:
                day_key = m.created_at.strftime("%Y-%m-%d")
                daily_counts[day_key] = daily_counts.get(day_key, 0) + 1

        most_active_day = None
        if daily_counts:
            most_active_day = max(daily_counts, key=daily_counts.get)

        return {
            "total_memories": count,
            "date_range": f"最近{days}天",
            "most_active_day": most_active_day,
            "category_breakdown": category_counts,
        }

    def get_by_id(self, memory_id: uuid.UUID) -> dict | None:
        """
        根据 ID 获取单条记忆

        Args:
            memory_id: 记忆ID

        Returns:
            记忆字典，未找到返回 None
        """
        if self.db is None:
            return None
        m = memory_repository.get_for_user(self.db, self.user_id, memory_id)
        if m is None:
            return None
        return {
            "id": str(m.id),
            "title": m.title or "",
            "content_raw": m.content_raw,
            "content_clean": m.content_clean,
            "content_summary": m.content_summary,
            "category": m.category,
            "tags": m.tags or [],
            "keywords": m.keywords or [],
            "entities": m.entities or [],
            "importance_score": m.importance_score,
            "source_type": m.source_type,
            "status": m.status,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "event_time": m.event_time.isoformat() if m.event_time else None,
            "time_info": m.time_info or {},
        }
