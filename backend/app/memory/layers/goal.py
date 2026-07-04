"""
Goal Memory - 目标记忆层 (新增)

核心职责:
1. 管理用户的长期目标和项目
2. 跟踪目标进度
3. 关联记忆到目标

特点:
- 目标有生命周期: active -> paused -> completed
- 支持目标优先级
- 记忆-目标多对多关联 (带相关性评分)

Phase 1: 调用 goal_repository 实现完整功能
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.repos.goal_repo import goal_repository


class GoalMemory:
    """
    目标记忆 - 用户的长期目标和项目

    使用示例:
        gm = GoalMemory(db, user_id)

        # 获取活跃目标
        goals = gm.get_active_goals(limit=5)

        # 创建新目标
        goal_id = gm.create_goal("完成项目A", "这是一个重要项目")

        # 关联记忆到目标
        gm.link_memory_to_goal(memory_id, goal_id, relevance_score=0.8)
    """

    def __init__(self, db: Session, user_id: uuid.UUID):
        self.db = db
        self.user_id = user_id

    def get_active_goals(self, limit: int = 10) -> list[dict]:
        """
        获取活跃目标

        Args:
            limit: 返回数量

        Returns:
            活跃目标列表 (字典格式)
        """
        if self.db is None:
            return []
        goals = goal_repository.list_active(self.db, self.user_id, limit=limit)
        return [
            {
                "id": str(g.id),
                "title": g.title,
                "description": g.description,
                "priority": g.priority,
                "status": g.status,
                "created_at": g.created_at.isoformat() if g.created_at else None,
                "updated_at": g.updated_at.isoformat() if g.updated_at else None,
            }
            for g in goals
        ]

    def get_all(self) -> list[dict]:
        """
        获取所有目标 (包括非活跃的)

        Returns:
            所有目标列表
        """
        if self.db is None:
            return []
        goals = goal_repository.list_all(self.db, self.user_id)
        return [
            {
                "id": str(g.id),
                "title": g.title,
                "description": g.description,
                "priority": g.priority,
                "status": g.status,
                "created_at": g.created_at.isoformat() if g.created_at else None,
            }
            for g in goals
        ]

    def create_goal(
        self,
        title: str,
        description: str = "",
        priority: int = 0,
    ) -> uuid.UUID:
        """
        创建新目标

        Args:
            title: 目标标题
            description: 目标描述
            priority: 优先级 (整数，越大越优先)

        Returns:
            新创建的目标ID
        """
        if self.db is None:
            raise RuntimeError("GoalMemory 需要数据库会话")
        goal = goal_repository.create(
            self.db,
            user_id=self.user_id,
            title=title,
            description=description or None,
            priority=priority,
        )
        return goal.id

    def update_goal(
        self,
        goal_id: uuid.UUID,
        title: str | None = None,
        description: str | None = None,
        priority: int | None = None,
        status: str | None = None,
    ) -> dict | None:
        """
        更新目标信息

        Args:
            goal_id: 目标ID
            title: 新标题 (可选)
            description: 新描述 (可选)
            priority: 新优先级 (可选)
            status: 新状态 (可选: active/paused/completed)

        Returns:
            更新后的目标字典，未找到返回 None
        """
        # 状态更新走专门的方法
        if status is not None:
            goal = goal_repository.update_status(
                self.db, goal_id, self.user_id, status
            )
        else:
            goal = goal_repository.update(
                self.db, goal_id, self.user_id,
                title=title, description=description, priority=priority,
            )
        if goal is None:
            return None
        return {
            "id": str(goal.id),
            "title": goal.title,
            "description": goal.description,
            "priority": goal.priority,
            "status": goal.status,
            "created_at": goal.created_at.isoformat() if goal.created_at else None,
            "updated_at": goal.updated_at.isoformat() if goal.updated_at else None,
        }

    def link_memory_to_goal(
        self,
        memory_id: uuid.UUID,
        goal_id: uuid.UUID,
        relevance_score: float = 1.0,
    ) -> dict:
        """
        关联记忆到目标 (幂等: 已存在则更新评分)

        Args:
            memory_id: 记忆ID
            goal_id: 目标ID
            relevance_score: 相关性评分 (0.0 ~ 1.0)

        Returns:
            关联信息字典
        """
        link = goal_repository.link_memory(
            self.db, goal_id, memory_id, relevance_score
        )
        return {
            "id": str(link.id),
            "memory_id": str(link.memory_id),
            "goal_id": str(link.goal_id),
            "relevance_score": link.relevance_score,
        }

    def unlink_memory_from_goal(
        self, memory_id: uuid.UUID, goal_id: uuid.UUID
    ) -> bool:
        """
        解除记忆与目标的关联

        Args:
            memory_id: 记忆ID
            goal_id: 目标ID

        Returns:
            True 表示成功
        """
        return goal_repository.unlink_memory(self.db, goal_id, memory_id)

    def get_goal_memories(self, goal_id: uuid.UUID) -> list[dict]:
        """
        获取目标关联的所有记忆

        Args:
            goal_id: 目标ID

        Returns:
            关联的记忆列表
        """
        links = goal_repository.get_linked_memories(self.db, goal_id, self.user_id)
        return [
            {
                "memory_id": str(link.memory_id),
                "goal_id": str(link.goal_id),
                "relevance_score": link.relevance_score,
            }
            for link in links
        ]

    def get_memory_goals(self, memory_id: uuid.UUID) -> list[dict]:
        """
        获取记忆关联的所有目标

        Args:
            memory_id: 记忆ID

        Returns:
            关联的目标列表
        """
        links = goal_repository.get_linked_goals(self.db, memory_id)
        return [
            {
                "memory_id": str(link.memory_id),
                "goal_id": str(link.goal_id),
                "relevance_score": link.relevance_score,
            }
            for link in links
        ]
