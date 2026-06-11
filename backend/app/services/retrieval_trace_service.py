from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.evaluation import RetrievalTrace
from app.repos.retrieval_trace_repo import retrieval_trace_repository
from app.schemas.qa import CitationItem, RetrievalTraceResponse
from app.services.agent_workflow_service import agent_workflow_service


class RetrievalTraceService:
    def record_qa_trace(
        self,
        db: Session,
        *,
        user_id: uuid.UUID,
        question: str,
        mode: str,
        hits,
        citations: list[CitationItem],
        answer_source: str,
        metadata: dict | None = None,
        candidate_annotations: dict[str, dict] | None = None,
    ) -> RetrievalTraceResponse:
        metadata_payload = dict(metadata or {})
        trace = RetrievalTrace(
            user_id=user_id,
            question=question,
            mode=mode,
            retrieval_strategy=metadata_payload.get("retrieval_strategy", "chunk_v1"),
            answer_source=answer_source,
            candidates=self._serialize_hits(hits, candidate_annotations or {}),
            selected_citations=[citation.model_dump() for citation in citations],
            meta_payload=metadata_payload,
        )
        retrieval_trace_repository.create(db, trace)
        workflow_steps = metadata_payload.get("workflow_steps") or []
        if workflow_steps:
            agent_run = agent_workflow_service.record_qa_run(
                db,
                user_id=user_id,
                retrieval_trace_id=trace.id,
                question=question,
                mode=mode,
                answer_source=answer_source,
                workflow_steps=workflow_steps,
                metadata={
                    "retrieval_strategy": trace.retrieval_strategy,
                    "answer_source": answer_source,
                },
                error_message=metadata_payload.get("agent_error_message"),
            )
            metadata_payload = {
                **metadata_payload,
                "agent_run_id": str(agent_run.id),
                "agent_run_status": agent_run.status,
                "agent_run_started_at": agent_run.started_at.isoformat() if agent_run.started_at else None,
                "agent_run_completed_at": agent_run.completed_at.isoformat() if agent_run.completed_at else None,
                "agent_run_duration_ms": agent_run.duration_ms,
                "agent_run_error_message": agent_run.error_message,
            }
            trace.meta_payload = metadata_payload
            db.flush()
        db.commit()
        db.refresh(trace)
        return self._to_response(trace)

    def list_recent(self, db: Session, user_id: uuid.UUID, limit: int = 20) -> list[RetrievalTraceResponse]:
        traces = retrieval_trace_repository.list_for_user(db, user_id, limit=limit)
        return [self._to_response(trace) for trace in traces]

    def _to_response(self, trace: RetrievalTrace) -> RetrievalTraceResponse:
        return RetrievalTraceResponse(
            id=str(trace.id),
            question=trace.question,
            mode=trace.mode,
            retrieval_strategy=trace.retrieval_strategy,
            answer_source=trace.answer_source,
            candidates=list(trace.candidates or []),
            selected_citations=list(trace.selected_citations or []),
            metadata=dict(trace.meta_payload or {}),
            created_at=trace.created_at.isoformat(),
        )

    def _serialize_hits(self, hits, candidate_annotations: dict[str, dict]) -> list[dict]:
        hit_scores = [float(hit.score) for hit in hits] or [1.0]
        max_hit_score = max(max(hit_scores), 1e-6)
        serialized = []
        for rank, hit in enumerate(hits, start=1):
            memory_id = str(hit.memory.id)
            annotation = candidate_annotations.get(memory_id, {})
            serialized.append(
                {
                    "rank": rank,
                    "memory_id": memory_id,
                    "chunk_id": str(hit.chunk.id),
                    "title": hit.memory.title or "Untitled Memory",
                    "category": hit.memory.category,
                    "score": round(float(hit.score), 6),
                    "raw_hit_score": round(float(hit.score), 6),
                    "normalized_hit_score": round(float(hit.score) / max_hit_score, 6),
                    "snippet": hit.chunk.chunk_summary or hit.chunk.chunk_text[:160],
                    "entered_direct_window": annotation.get("entered_direct_window"),
                    "entered_rerank": annotation.get("entered_rerank"),
                    "final_selected": annotation.get("final_selected"),
                    "exclusion_reason": annotation.get("exclusion_reason"),
                    "exclusion_reason_detail": annotation.get("exclusion_reason_detail"),
                    "citation_source": annotation.get("citation_source"),
                    "final_score": annotation.get("final_score"),
                }
            )
        return serialized


retrieval_trace_service = RetrievalTraceService()
