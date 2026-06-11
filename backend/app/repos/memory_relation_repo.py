import uuid

from sqlalchemy import delete, desc, func, or_, select
from sqlalchemy.orm import Session

from app.models.memory import MemoryRelation


class MemoryRelationRepository:
    def count_all(self, db: Session) -> int:
        stmt = select(func.count(MemoryRelation.id))
        return int(db.execute(stmt).scalar_one())

    def list_from_memory(
        self,
        db: Session,
        user_id: uuid.UUID,
        memory_id: uuid.UUID,
        *,
        limit: int = 8,
    ) -> list[MemoryRelation]:
        stmt = (
            select(MemoryRelation)
            .where(
                MemoryRelation.user_id == user_id,
                MemoryRelation.from_memory_id == memory_id,
            )
            .order_by(desc(MemoryRelation.score), desc(MemoryRelation.created_at))
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())

    def delete_for_memory(self, db: Session, user_id: uuid.UUID, memory_id: uuid.UUID) -> int:
        result = db.execute(
            delete(MemoryRelation).where(
                MemoryRelation.user_id == user_id,
                or_(
                    MemoryRelation.from_memory_id == memory_id,
                    MemoryRelation.to_memory_id == memory_id,
                ),
            )
        )
        return int(result.rowcount or 0)

    def create_many(self, db: Session, relations: list[MemoryRelation]) -> list[MemoryRelation]:
        for relation in relations:
            db.add(relation)
        db.flush()
        return relations


memory_relation_repository = MemoryRelationRepository()
