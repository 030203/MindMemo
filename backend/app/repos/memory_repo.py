import uuid

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.memory import MemoryItem


class MemoryRepository:
    def list_for_user(
        self,
        db: Session,
        user_id: uuid.UUID,
        query_text: str | None = None,
        category: str | None = None,
    ) -> list[MemoryItem]:
        stmt = (
            select(MemoryItem)
            .where(MemoryItem.user_id == user_id, MemoryItem.deleted_at.is_(None))
            .order_by(desc(MemoryItem.created_at))
        )

        normalized_category = (category or "").strip().lower()
        if normalized_category and normalized_category != "all":
            stmt = stmt.where(MemoryItem.category == normalized_category)

        normalized_query = (query_text or "").strip()
        if normalized_query:
            pattern = f"%{normalized_query}%"
            stmt = stmt.where(
                or_(
                    MemoryItem.title.ilike(pattern),
                    MemoryItem.content_summary.ilike(pattern),
                    MemoryItem.content_raw.ilike(pattern),
                )
            )

        return list(db.execute(stmt).scalars().all())

    def get_for_user(self, db: Session, user_id: uuid.UUID, memory_id: uuid.UUID) -> MemoryItem | None:
        stmt = select(MemoryItem).where(
            MemoryItem.id == memory_id,
            MemoryItem.user_id == user_id,
            MemoryItem.deleted_at.is_(None),
        )
        return db.execute(stmt).scalar_one_or_none()

    def list_all_active(self, db: Session) -> list[MemoryItem]:
        stmt = (
            select(MemoryItem)
            .where(MemoryItem.deleted_at.is_(None), MemoryItem.status == "active")
            .order_by(desc(MemoryItem.created_at))
        )
        return list(db.execute(stmt).scalars().all())

    def create(self, db: Session, memory: MemoryItem) -> MemoryItem:
        db.add(memory)
        db.flush()
        db.refresh(memory)
        return memory

    def count_recent(self, db: Session, user_id: uuid.UUID, created_after) -> int:
        stmt = select(func.count(MemoryItem.id)).where(
            MemoryItem.user_id == user_id,
            MemoryItem.deleted_at.is_(None),
            MemoryItem.created_at >= created_after,
        )
        return int(db.execute(stmt).scalar_one())


memory_repository = MemoryRepository()
