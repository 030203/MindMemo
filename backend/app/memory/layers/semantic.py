"""
Semantic Memory - 语义记忆层

核心职责:
1. 提供结构化知识查询 (标签、关键词、实体)
2. 管理用户画像
3. 提供语义层面的摘要统计

特点:
- 从 memory_items 中提取结构化信息
- 聚合标签、实体等维度的知识
- 为用户画像和 Agent 决策提供知识背景

Phase 1: 调用现有 memory_repository 实现真实数据访问
"""
from __future__ import annotations

import uuid
from collections import Counter
from typing import Optional

from sqlalchemy.orm import Session

from app.repos.memory_repo import memory_repository


class SemanticMemory:
    """
    语义记忆 - 结构化知识和用户画像

    使用示例:
        sm = SemanticMemory(db, user_id)

        # 获取用户画像
        profile = sm.get_user_profile()

        # 获取标签/实体统计
        summary = sm.get_summary()
    """

    def __init__(self, db: Session, user_id: uuid.UUID):
        self.db = db
        self.user_id = user_id

    def get_user_profile(self) -> dict:
        """
        获取用户画像 (从记忆数据中聚合提取)

        提取维度:
        - 兴趣: 从高频标签和关键词推断
        - 常用实体: 从 entities 字段聚合
        - 活跃类别: 从 category 分布推断
        - 活跃目标: 从 goal 关联获取

        Returns:
            用户画像字典
        """
        if self.db is None:
            return {"interests": [], "frequent_keywords": [], "frequent_entities": [], "category_distribution": {}, "total_memories": 0}
        memories = memory_repository.list_for_user(self.db, self.user_id)

        # 聚合标签
        tag_counter: Counter = Counter()
        keyword_counter: Counter = Counter()
        entity_counter: Counter = Counter()
        category_counter: Counter = Counter()

        for m in memories:
            for tag in (m.tags or []):
                tag_counter[tag] += 1
            for kw in (m.keywords or []):
                keyword_counter[kw] += 1
            for ent in (m.entities or []):
                entity_counter[ent] += 1
            category_counter[m.category or "other"] += 1

        return {
            "interests": [tag for tag, _ in tag_counter.most_common(10)],
            "frequent_keywords": [kw for kw, _ in keyword_counter.most_common(10)],
            "frequent_entities": [ent for ent, _ in entity_counter.most_common(10)],
            "category_distribution": dict(category_counter.most_common()),
            "total_memories": len(memories),
        }

    def get_summary(self) -> dict:
        """
        获取语义记忆摘要

        Returns:
            包含标签、关键词、实体、类别统计的字典
        """
        if self.db is None:
            return {"total_memories": 0, "unique_tags": 0, "unique_entities": 0, "top_tags": [], "top_entities": [], "categories": {}}
        memories = memory_repository.list_for_user(self.db, self.user_id)

        tag_counter: Counter = Counter()
        entity_counter: Counter = Counter()
        category_counter: Counter = Counter()

        for m in memories:
            for tag in (m.tags or []):
                tag_counter[tag] += 1
            for ent in (m.entities or []):
                entity_counter[ent] += 1
            category_counter[m.category or "other"] += 1

        return {
            "total_memories": len(memories),
            "unique_tags": len(tag_counter),
            "unique_entities": len(entity_counter),
            "top_tags": tag_counter.most_common(10),
            "top_entities": entity_counter.most_common(10),
            "categories": dict(category_counter.most_common()),
        }

    def search_by_tag(self, tag: str, limit: int = 10) -> list[dict]:
        """
        按标签搜索记忆

        Args:
            tag: 标签名称
            limit: 返回数量

        Returns:
            匹配的记忆列表
        """
        if self.db is None:
            return []
        memories = memory_repository.list_for_user(self.db, self.user_id)
        matched = [m for m in memories if tag in (m.tags or [])]
        return [
            {
                "id": str(m.id),
                "title": m.title or "",
                "summary": m.content_summary or "",
                "tags": m.tags or [],
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in matched[:limit]
        ]

    def search_by_entity(self, entity: str, limit: int = 10) -> list[dict]:
        """
        按实体搜索记忆

        Args:
            entity: 实体名称
            limit: 返回数量

        Returns:
            匹配的记忆列表
        """
        if self.db is None:
            return []
        memories = memory_repository.list_for_user(self.db, self.user_id)
        matched = [m for m in memories if entity in (m.entities or [])]
        return [
            {
                "id": str(m.id),
                "title": m.title or "",
                "summary": m.content_summary or "",
                "entities": m.entities or [],
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in matched[:limit]
        ]
