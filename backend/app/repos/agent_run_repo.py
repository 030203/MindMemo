import uuid

from sqlalchemy import asc, desc, select
from sqlalchemy.orm import Session

from app.models.evaluation import AgentRun, AgentRunStep


class AgentRunRepository:
    def create(self, db: Session, run: AgentRun) -> AgentRun:
        db.add(run)
        db.flush()
        db.refresh(run)
        return run

    def create_steps(self, db: Session, steps: list[AgentRunStep]) -> list[AgentRunStep]:
        if not steps:
            return []
        db.add_all(steps)
        db.flush()
        return steps

    def get_for_user(self, db: Session, user_id: uuid.UUID, run_id: uuid.UUID) -> AgentRun | None:
        stmt = select(AgentRun).where(AgentRun.user_id == user_id, AgentRun.id == run_id)
        return db.execute(stmt).scalar_one_or_none()

    def list_for_user(self, db: Session, user_id: uuid.UUID, limit: int = 20) -> list[AgentRun]:
        stmt = (
            select(AgentRun)
            .where(AgentRun.user_id == user_id)
            .order_by(desc(AgentRun.created_at))
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())

    def list_steps(self, db: Session, user_id: uuid.UUID, run_id: uuid.UUID) -> list[AgentRunStep]:
        stmt = (
            select(AgentRunStep)
            .where(AgentRunStep.user_id == user_id, AgentRunStep.run_id == run_id)
            .order_by(asc(AgentRunStep.step_index))
        )
        return list(db.execute(stmt).scalars().all())


agent_run_repository = AgentRunRepository()
