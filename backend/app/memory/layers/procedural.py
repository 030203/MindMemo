"""
Procedural Memory - 程序记忆层

核心职责:
1. 封装 todos 和 reminders 表
2. 提供任务和提醒查询
3. 支持待办管理

特点:
- 持久化存储
- 支持状态管理 (pending/doing/done/blocked)
- 支持定时提醒

Phase 1: 调用现有 todo_repository 和 reminder_repository
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.repos.todo_repo import todo_repository
from app.repos.reminder_repo import reminder_repository


class ProceduralMemory:
    """
    程序记忆 - 任务和提醒

    使用示例:
        pm = ProceduralMemory(db, user_id)

        # 获取待办任务
        todos = pm.get_pending_todos(limit=10)

        # 获取即将到来的提醒
        reminders = pm.get_upcoming_reminders(days=7)
    """

    def __init__(self, db: Session, user_id: uuid.UUID):
        self.db = db
        self.user_id = user_id

    def get_pending_todos(self, limit: int = 10) -> list[dict]:
        """
        获取待办任务 (pending + doing + blocked)

        Args:
            limit: 返回数量

        Returns:
            待办任务列表
        """
        if self.db is None:
            return []
        # list_for_user with default sort=priority already filters non-done
        todos = todo_repository.list_for_user(
            self.db, self.user_id, status="all"
        )
        # Filter to non-done statuses
        active = [t for t in todos if t.status != "done"][:limit]
        return [
            {
                "id": str(t.id),
                "title": t.title,
                "description": t.description,
                "status": t.status,
                "priority": t.priority,
                "due_at": t.due_at.isoformat() if t.due_at else None,
                "source_memory_id": str(t.source_memory_id) if t.source_memory_id else None,
                "risk_level": t.risk_level,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in active
        ]

    def get_upcoming_reminders(self, days: int = 7) -> list[dict]:
        """
        获取即将到来的提醒 (未来 N 天内)

        Args:
            days: 时间范围 (天)

        Returns:
            提醒列表
        """
        if self.db is None:
            return []
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=days)

        reminders = reminder_repository.list_for_user(
            self.db, self.user_id, active_only=True
        )
        # 过滤未来 N 天内的提醒
        upcoming = [
            r for r in reminders
            if r.due_at is not None and now <= r.due_at <= cutoff
        ]
        return [
            {
                "id": str(r.id),
                "todo_id": str(r.todo_id),
                "reminder_type": r.reminder_type,
                "level": r.level,
                "title": r.title,
                "message": r.message,
                "due_at": r.due_at.isoformat() if r.due_at else None,
                "status": r.status,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            }
            for r in upcoming
        ]

    def get_todo_by_id(self, todo_id: uuid.UUID) -> dict | None:
        """
        根据 ID 获取单个待办

        Args:
            todo_id: 待办ID

        Returns:
            待办字典，未找到返回 None
        """
        if self.db is None:
            return None
        t = todo_repository.get_for_user(self.db, self.user_id, todo_id)
        if t is None:
            return None
        return {
            "id": str(t.id),
            "title": t.title,
            "description": t.description,
            "status": t.status,
            "priority": t.priority,
            "due_at": t.due_at.isoformat() if t.due_at else None,
            "source_memory_id": str(t.source_memory_id) if t.source_memory_id else None,
            "risk_level": t.risk_level,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
        }
