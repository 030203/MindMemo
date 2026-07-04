import uuid

from sqlalchemy import case, desc, or_, select
from sqlalchemy.orm import Session

from app.models.todo import TodoItem
from app.models.base import utcnow


class TodoRepository:
    def list_for_user(
        self,
        db: Session,
        user_id: uuid.UUID,
        query_text: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        sort: str | None = "priority",
        exclude_reminders: bool = False,
    ) -> list[TodoItem]:
        stmt = (
            select(TodoItem)
            .where(TodoItem.user_id == user_id, TodoItem.deleted_at.is_(None))
        )

        if exclude_reminders:
            stmt = stmt.where(TodoItem.remind_at.is_(None))

        normalized_status = (status or "").strip().lower()
        if normalized_status and normalized_status != "all":
            stmt = stmt.where(TodoItem.status == normalized_status)

        normalized_priority = (priority or "").strip().lower()
        if normalized_priority and normalized_priority != "all":
            if normalized_priority == "attention":
                stmt = stmt.where(or_(TodoItem.priority.in_(["high", "urgent"]), TodoItem.risk_level == "high"))
            else:
                stmt = stmt.where(TodoItem.priority == normalized_priority)

        normalized_query = (query_text or "").strip()
        if normalized_query:
            pattern = f"%{normalized_query}%"
            stmt = stmt.where(
                or_(
                    TodoItem.title.ilike(pattern),
                    TodoItem.description.ilike(pattern),
                )
            )

        normalized_sort = (sort or "priority").strip().lower()
        if normalized_sort == "newest":
            stmt = stmt.order_by(desc(TodoItem.created_at))
        elif normalized_sort == "due":
            stmt = stmt.order_by(TodoItem.due_at.is_(None), TodoItem.due_at.asc(), desc(TodoItem.created_at))
        else:
            status_rank = case(
                (TodoItem.status == "doing", 0),
                (TodoItem.status == "pending", 1),
                (TodoItem.status == "blocked", 2),
                (TodoItem.status == "done", 3),
                else_=4,
            )
            priority_rank = case(
                (TodoItem.priority == "urgent", 0),
                (TodoItem.priority == "high", 1),
                (TodoItem.priority == "medium", 2),
                (TodoItem.priority == "low", 3),
                else_=4,
            )
            stmt = stmt.order_by(
                status_rank,
                priority_rank,
                TodoItem.due_at.is_(None),
                TodoItem.due_at.asc(),
                desc(TodoItem.created_at),
            )

        return list(db.execute(stmt).scalars().all())

    def list_all_active(self, db: Session) -> list[TodoItem]:
        stmt = (
            select(TodoItem)
            .where(TodoItem.deleted_at.is_(None), TodoItem.status != "done")
            .order_by(desc(TodoItem.created_at))
        )
        return list(db.execute(stmt).scalars().all())

    def get_for_user(self, db: Session, user_id: uuid.UUID, todo_id: uuid.UUID) -> TodoItem | None:
        stmt = select(TodoItem).where(
            TodoItem.id == todo_id,
            TodoItem.user_id == user_id,
            TodoItem.deleted_at.is_(None),
        )
        return db.execute(stmt).scalar_one_or_none()

    def get_for_source_memory(self, db: Session, user_id: uuid.UUID, memory_id: uuid.UUID) -> TodoItem | None:
        stmt = select(TodoItem).where(
            TodoItem.user_id == user_id,
            TodoItem.source_memory_id == memory_id,
            TodoItem.deleted_at.is_(None),
        )
        return db.execute(stmt).scalar_one_or_none()

    def create(self, db: Session, todo: TodoItem) -> TodoItem:
        db.add(todo)
        db.flush()
        db.refresh(todo)
        return todo

    def soft_delete(self, db: Session, todo: TodoItem) -> None:
        todo.deleted_at = utcnow()
        db.flush()


todo_repository = TodoRepository()
