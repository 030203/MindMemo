"""
GoalRepository - 目标数据访问层

Phase 1 新增: 分层记忆重构

核心职责:
1. 目标的 CRUD 操作
2. 记忆-目标关联管理
3. 按状态/优先级查询

设计原则:
- 所有操作都按 user_id 隔离
- 关联操作支持相关性评分
- 遵循项目单例模式
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.goal import Goal, MemoryGoalLink


class GoalRepository:
    """目标仓库 - 管理用户目标和记忆关联"""

    # ── 目标 CRUD ─────────────────────────────────────────────

    def create(
        self,
        db: Session,
        user_id: uuid.UUID,
        title: str,
        description: str | None = None,
        priority: int = 0,
    ) -> Goal:
        """
        创建新目标

        Args:
            db: 数据库会话
            user_id: 用户ID
            title: 目标标题
            description: 目标描述 (可选)
            priority: 优先级 (整数，越大越优先)

        Returns:
            新创建的 Goal 实例
        """
        goal = Goal(
            user_id=user_id,
            title=title,
            description=description,
            priority=priority,
            status="active",
        )
        db.add(goal)
        db.commit()
        db.refresh(goal)
        return goal

    def get_by_id(self, db: Session, goal_id: uuid.UUID, user_id: uuid.UUID) -> Goal | None:
        """
        根据 ID 获取目标 (用户隔离)

        Args:
            db: 数据库会话
            goal_id: 目标ID
            user_id: 用户ID (用于权限校验)

        Returns:
            Goal 实例，未找到返回 None
        """
        return (
            db.query(Goal)
            .filter(Goal.id == goal_id, Goal.user_id == user_id)
            .first()
        )

    def list_active(
        self, db: Session, user_id: uuid.UUID, limit: int = 10
    ) -> list[Goal]:
        """
        获取活跃目标 (按优先级和时间排序)

        Args:
            db: 数据库会话
            user_id: 用户ID
            limit: 返回数量上限

        Returns:
            活跃目标列表 (优先级高 > 创建时间新)
        """
        return (
            db.query(Goal)
            .filter(Goal.user_id == user_id, Goal.status == "active")
            .order_by(desc(Goal.priority), desc(Goal.created_at))
            .limit(limit)
            .all()
        )

    def list_all(self, db: Session, user_id: uuid.UUID) -> list[Goal]:
        """
        获取所有目标 (包括非活跃的)

        Args:
            db: 数据库会话
            user_id: 用户ID

        Returns:
            所有目标列表 (按创建时间倒序)
        """
        return (
            db.query(Goal)
            .filter(Goal.user_id == user_id)
            .order_by(desc(Goal.created_at))
            .all()
        )

    def update_status(
        self, db: Session, goal_id: uuid.UUID, user_id: uuid.UUID, status: str
    ) -> Goal | None:
        """
        更新目标状态

        Args:
            db: 数据库会话
            goal_id: 目标ID
            user_id: 用户ID
            status: 新状态 (active / paused / completed)

        Returns:
            更新后的 Goal 实例，未找到返回 None
        """
        goal = self.get_by_id(db, goal_id, user_id)
        if goal is None:
            return None
        goal.status = status
        db.commit()
        db.refresh(goal)
        return goal

    def update(
        self,
        db: Session,
        goal_id: uuid.UUID,
        user_id: uuid.UUID,
        title: str | None = None,
        description: str | None = None,
        priority: int | None = None,
    ) -> Goal | None:
        """
        更新目标信息

        Args:
            db: 数据库会话
            goal_id: 目标ID
            user_id: 用户ID
            title: 新标题 (可选)
            description: 新描述 (可选)
            priority: 新优先级 (可选)

        Returns:
            更新后的 Goal 实例，未找到返回 None
        """
        goal = self.get_by_id(db, goal_id, user_id)
        if goal is None:
            return None
        if title is not None:
            goal.title = title
        if description is not None:
            goal.description = description
        if priority is not None:
            goal.priority = priority
        db.commit()
        db.refresh(goal)
        return goal

    # ── 记忆-目标关联 ─────────────────────────────────────────

    def link_memory(
        self,
        db: Session,
        goal_id: uuid.UUID,
        memory_id: uuid.UUID,
        relevance_score: float = 1.0,
    ) -> MemoryGoalLink:
        """
        将记忆关联到目标 (幂等: 已存在则更新评分)

        Args:
            db: 数据库会话
            goal_id: 目标ID
            memory_id: 记忆ID
            relevance_score: 相关性评分 (0.0 ~ 1.0)

        Returns:
            MemoryGoalLink 实例
        """
        # 检查是否已存在关联
        existing = (
            db.query(MemoryGoalLink)
            .filter(
                MemoryGoalLink.memory_id == memory_id,
                MemoryGoalLink.goal_id == goal_id,
            )
            .first()
        )
        if existing is not None:
            existing.relevance_score = relevance_score
            db.commit()
            db.refresh(existing)
            return existing

        link = MemoryGoalLink(
            goal_id=goal_id,
            memory_id=memory_id,
            relevance_score=relevance_score,
        )
        db.add(link)
        db.commit()
        db.refresh(link)
        return link

    def unlink_memory(
        self, db: Session, goal_id: uuid.UUID, memory_id: uuid.UUID
    ) -> bool:
        """
        解除记忆与目标的关联

        Args:
            db: 数据库会话
            goal_id: 目标ID
            memory_id: 记忆ID

        Returns:
            True 表示成功删除，False 表示未找到关联
        """
        link = (
            db.query(MemoryGoalLink)
            .filter(
                MemoryGoalLink.memory_id == memory_id,
                MemoryGoalLink.goal_id == goal_id,
            )
            .first()
        )
        if link is None:
            return False
        db.delete(link)
        db.commit()
        return True

    def get_linked_memories(
        self, db: Session, goal_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[MemoryGoalLink]:
        """
        获取目标关联的所有记忆

        Args:
            db: 数据库会话
            goal_id: 目标ID
            user_id: 用户ID (用于权限校验)

        Returns:
            MemoryGoalLink 列表
        """
        return (
            db.query(MemoryGoalLink)
            .join(Goal)
            .filter(Goal.id == goal_id, Goal.user_id == user_id)
            .order_by(desc(MemoryGoalLink.relevance_score))
            .all()
        )

    def get_linked_goals(
        self, db: Session, memory_id: uuid.UUID
    ) -> list[MemoryGoalLink]:
        """
        获取记忆关联的所有目标

        Args:
            db: 数据库会话
            memory_id: 记忆ID

        Returns:
            MemoryGoalLink 列表
        """
        return (
            db.query(MemoryGoalLink)
            .filter(MemoryGoalLink.memory_id == memory_id)
            .order_by(desc(MemoryGoalLink.relevance_score))
            .all()
        )


# 全局单例 (遵循项目约定)
goal_repository = GoalRepository()
