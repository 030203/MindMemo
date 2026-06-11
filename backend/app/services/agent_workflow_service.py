from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.evaluation import AgentRun, AgentRunStep
from app.repos.agent_run_repo import agent_run_repository


class AgentWorkflowService:
    def record_qa_run(
        self,
        db: Session,
        *,
        user_id: uuid.UUID,
        retrieval_trace_id: uuid.UUID,
        question: str,
        mode: str,
        answer_source: str,
        workflow_steps: list[dict],
        metadata: dict | None = None,
        error_message: str | None = None,
    ) -> AgentRun:
        normalized_steps = self._normalize_steps(workflow_steps)
        started_at, completed_at, duration_ms = self._derive_run_timing(normalized_steps)
        run = AgentRun(
            user_id=user_id,
            retrieval_trace_id=retrieval_trace_id,
            run_type="qa_agentic_rag",
            question=question,
            mode=mode,
            status=self._derive_status(normalized_steps),
            answer_source=answer_source,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            error_message=error_message or self._derive_error_message(normalized_steps),
            meta_payload={
                "step_count": len(normalized_steps),
                "source": "retrieval_trace_service",
                **(metadata or {}),
            },
        )
        agent_run_repository.create(db, run)
        steps = [
            AgentRunStep(
                user_id=user_id,
                run_id=run.id,
                step_index=index,
                step_key=step["key"],
                label=step["label"],
                status=step["status"],
                detail=step["detail"],
                metric=step.get("metric"),
                started_at=step.get("started_at"),
                completed_at=step.get("completed_at"),
                duration_ms=step.get("duration_ms"),
                error_message=step.get("error_message"),
                meta_payload=step.get("metadata") or {},
            )
            for index, step in enumerate(normalized_steps, start=1)
        ]
        agent_run_repository.create_steps(db, steps)
        return run

    def serialize_run(self, db: Session, user_id: uuid.UUID, run: AgentRun) -> dict:
        steps = agent_run_repository.list_steps(db, user_id, run.id)
        return {
            "id": str(run.id),
            "retrieval_trace_id": str(run.retrieval_trace_id) if run.retrieval_trace_id else None,
            "run_type": run.run_type,
            "question": run.question,
            "mode": run.mode,
            "status": run.status,
            "answer_source": run.answer_source,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "duration_ms": run.duration_ms,
            "error_message": run.error_message,
            "metadata": dict(run.meta_payload or {}),
            "steps": [
                {
                    "id": str(step.id),
                    "step_index": step.step_index,
                    "key": step.step_key,
                    "label": step.label,
                    "status": step.status,
                    "detail": step.detail,
                    "metric": step.metric,
                    "started_at": step.started_at.isoformat() if step.started_at else None,
                    "completed_at": step.completed_at.isoformat() if step.completed_at else None,
                    "duration_ms": step.duration_ms,
                    "error_message": step.error_message,
                    "metadata": dict(step.meta_payload or {}),
                }
                for step in steps
            ],
        }

    def _normalize_steps(self, workflow_steps: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        for index, raw_step in enumerate(workflow_steps, start=1):
            if not isinstance(raw_step, dict):
                continue
            key = str(raw_step.get("key") or f"step_{index}").strip()
            label = str(raw_step.get("label") or key).strip()
            status = str(raw_step.get("status") or "done").strip()
            detail = str(raw_step.get("detail") or "").strip()
            metric = raw_step.get("metric")
            started_at = self._coerce_datetime(raw_step.get("started_at"))
            completed_at = self._coerce_datetime(raw_step.get("completed_at"))
            duration_ms = self._coerce_duration_ms(raw_step.get("duration_ms"))
            normalized.append(
                {
                    "key": key[:64] or f"step_{index}",
                    "label": label[:120] or f"Step {index}",
                    "status": status[:32] or "done",
                    "detail": detail,
                    "metric": str(metric)[:120] if metric is not None else None,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "duration_ms": duration_ms,
                    "error_message": self._coerce_error_message(raw_step.get("error_message")),
                    "metadata": dict(raw_step.get("metadata") or {}),
                }
            )
        return normalized

    def _derive_status(self, steps: list[dict]) -> str:
        if any(step.get("status") in {"failed", "error"} for step in steps):
            return "failed"
        if any(step.get("status") in {"running", "pending"} for step in steps):
            return "running"
        return "completed"

    def _derive_run_timing(self, steps: list[dict]) -> tuple[datetime, datetime | None, float | None]:
        started_candidates = [step["started_at"] for step in steps if step.get("started_at") is not None]
        completed_candidates = [step["completed_at"] for step in steps if step.get("completed_at") is not None]
        started_at = min(started_candidates) if started_candidates else utcnow()
        completed_at = max(completed_candidates) if completed_candidates else None
        if completed_at is None:
            return started_at, None, None
        duration_ms = max((completed_at - started_at).total_seconds() * 1000.0, 0.0)
        return started_at, completed_at, round(duration_ms, 3)

    def _derive_error_message(self, steps: list[dict]) -> str | None:
        for step in steps:
            if step.get("status") in {"failed", "error"} and step.get("error_message"):
                return step["error_message"]
        return None

    def _coerce_datetime(self, value) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    def _coerce_duration_ms(self, value) -> float | None:
        if value is None:
            return None
        try:
            return round(max(float(value), 0.0), 3)
        except (TypeError, ValueError):
            return None

    def _coerce_error_message(self, value) -> str | None:
        if value is None:
            return None
        message = str(value).strip()
        return message or None


agent_workflow_service = AgentWorkflowService()
