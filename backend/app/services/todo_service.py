from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.timeline import TimelineEvent
from app.models.todo import TodoItem
from app.repos.timeline_repo import timeline_repository
from app.repos.todo_repo import todo_repository
from app.schemas.todo import TodoCreateRequest, TodoResponse, TodoUpdateRequest


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_todo_response(todo: TodoItem) -> TodoResponse:
    return TodoResponse(
        id=str(todo.id),
        title=todo.title,
        description=todo.description or "",
        status=todo.status,
        priority=todo.priority,
        due_at=todo.due_at,
        risk_level=todo.risk_level,
        source_memory_id=str(todo.source_memory_id) if todo.source_memory_id is not None else None,
    )


def _derive_risk_level(priority: str, due_at) -> str:
    if priority == "urgent":
        return "high"
    if priority == "high":
        return "medium"
    if due_at is not None:
        return "medium"
    return "low"


class TodoService:
    def list_todos(
        self,
        db: Session,
        user_id: uuid.UUID,
        query_text: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        sort: str | None = "priority",
    ) -> list[TodoResponse]:
        todos = todo_repository.list_for_user(db, user_id, query_text=query_text, status=status, priority=priority, sort=sort, exclude_reminders=True)
        return [_to_todo_response(todo) for todo in todos]

    def create_todo(self, db: Session, user_id: uuid.UUID, payload: TodoCreateRequest) -> TodoResponse:
        todo = TodoItem(
            user_id=user_id,
            title=payload.title,
            description=payload.description,
            status="pending",
            priority=payload.priority,
            due_at=payload.due_at,
            source_memory_id=uuid.UUID(payload.source_memory_id) if payload.source_memory_id else None,
            risk_level=_derive_risk_level(payload.priority, payload.due_at),
        )
        todo_repository.create(db, todo)
        timeline_repository.create(
            db,
            TimelineEvent(
                user_id=user_id,
                event_type="todo_created",
                ref_type="todo",
                ref_id=todo.id,
                title=f"创建任务：{todo.title}",
                summary=todo.description or "新任务已进入待办列表。",
                event_time=utcnow(),
            ),
        )
        db.commit()
        db.refresh(todo)
        return _to_todo_response(todo)

    def complete_todo(self, db: Session, user_id: uuid.UUID, todo_id: str) -> TodoResponse | None:
        todo = todo_repository.get_for_user(db, user_id, uuid.UUID(todo_id))
        if todo is None:
            return None

        todo.status = "done"
        todo.completed_at = utcnow()
        timeline_repository.create(
            db,
            TimelineEvent(
                user_id=user_id,
                event_type="todo_done",
                ref_type="todo",
                ref_id=todo.id,
                title=f"完成任务：{todo.title}",
                summary="该任务已被标记完成。",
                event_time=utcnow(),
            ),
        )
        db.commit()
        db.refresh(todo)
        return _to_todo_response(todo)

    def update_todo(self, db: Session, user_id: uuid.UUID, todo_id: str, payload: TodoUpdateRequest) -> TodoResponse | None:
        todo = todo_repository.get_for_user(db, user_id, uuid.UUID(todo_id))
        if todo is None:
            return None

        previous_status = todo.status
        todo.title = payload.title.strip() or todo.title
        todo.description = payload.description
        todo.priority = payload.priority
        todo.status = payload.status
        todo.due_at = payload.due_at
        todo.source_memory_id = uuid.UUID(payload.source_memory_id) if payload.source_memory_id else None
        todo.risk_level = _derive_risk_level(payload.priority, payload.due_at)

        if payload.status == "done":
            todo.completed_at = todo.completed_at or utcnow()
        else:
            todo.completed_at = None

        if previous_status != payload.status:
            timeline_repository.create(
                db,
                TimelineEvent(
                    user_id=user_id,
                    event_type="todo_done" if payload.status == "done" else "todo_created",
                    ref_type="todo",
                    ref_id=todo.id,
                    title=f"更新任务状态：{todo.title}",
                    summary=f"任务现在是“{payload.status}”状态。",
                    event_time=utcnow(),
                ),
            )

        db.commit()
        db.refresh(todo)
        return _to_todo_response(todo)

    def create_from_ingest(
        self,
        db: Session,
        *,
        user_id: uuid.UUID,
        source_memory_id: uuid.UUID,
        title: str,
        due_at: datetime | None = None,
        remind_at: datetime | None = None,
    ) -> TodoItem:
        """从文本录入直接创建 todo/reminder，跳过 LLM 分类步骤。"""
        # reminder 类型：due_at 和 remind_at 保持一致，让提醒系统能识别
        effective_due_at = remind_at if remind_at is not None else due_at
        todo = TodoItem(
            id=uuid.uuid4(),
            user_id=user_id,
            source_memory_id=source_memory_id,
            title=title[:255],
            status="pending",
            priority="medium",
            due_at=effective_due_at,
            remind_at=remind_at,
            risk_level=_derive_risk_level("medium", due_at),
            ai_generated=False,
            requires_approval=False,
        )
        db.add(todo)
        db.commit()
        db.refresh(todo)
        return todo

    def delete_todo(self, db: Session, user_id: uuid.UUID, todo_id: str) -> bool:
        todo = todo_repository.get_for_user(db, user_id, uuid.UUID(todo_id))
        if todo is None:
            return False
        todo_repository.soft_delete(db, todo)
        timeline_repository.create(
            db,
            TimelineEvent(
                user_id=user_id,
                event_type="todo_deleted",
                ref_type="todo",
                ref_id=todo.id,
                title=f"删除任务：{todo.title}",
                summary="该任务已从当前待办列表移除。",
                event_time=utcnow(),
            ),
        )
        db.commit()
        return True


todo_service = TodoService()
