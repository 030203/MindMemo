import uuid

from sqlalchemy import delete, desc, select
from sqlalchemy.orm import Session

from app.models.memory import ExtractedFact


class FactRepository:
    def list_for_memory(self, db: Session, user_id: uuid.UUID, memory_id: uuid.UUID) -> list[ExtractedFact]:
        stmt = (
            select(ExtractedFact)
            .where(ExtractedFact.user_id == user_id, ExtractedFact.memory_id == memory_id)
            .order_by(desc(ExtractedFact.confidence_score), desc(ExtractedFact.created_at))
        )
        return list(db.execute(stmt).scalars().all())

    def list_for_user(
        self,
        db: Session,
        user_id: uuid.UUID,
        *,
        fact_type: str | None = None,
    ) -> list[ExtractedFact]:
        stmt = select(ExtractedFact).where(ExtractedFact.user_id == user_id)
        if fact_type:
            stmt = stmt.where(ExtractedFact.fact_type == fact_type)
        stmt = stmt.order_by(desc(ExtractedFact.event_time), desc(ExtractedFact.created_at))
        return list(db.execute(stmt).scalars().all())

    def replace_for_memory(self, db: Session, user_id: uuid.UUID, memory_id: uuid.UUID, facts: list[ExtractedFact]) -> int:
        db.execute(
            delete(ExtractedFact).where(
                ExtractedFact.user_id == user_id,
                ExtractedFact.memory_id == memory_id,
            )
        )
        for fact in facts:
            db.add(fact)
        db.flush()
        return len(facts)


fact_repository = FactRepository()
