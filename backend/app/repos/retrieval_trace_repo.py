import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.evaluation import RetrievalTrace


class RetrievalTraceRepository:
    def create(self, db: Session, trace: RetrievalTrace) -> RetrievalTrace:
        db.add(trace)
        db.flush()
        db.refresh(trace)
        return trace

    def list_for_user(self, db: Session, user_id: uuid.UUID, limit: int = 20) -> list[RetrievalTrace]:
        stmt = (
            select(RetrievalTrace)
            .where(RetrievalTrace.user_id == user_id)
            .order_by(desc(RetrievalTrace.created_at))
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())


retrieval_trace_repository = RetrievalTraceRepository()
