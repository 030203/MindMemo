from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.repos.agent_run_repo import agent_run_repository
from app.schemas.common import ApiResponse
from app.schemas.qa import AgentRunResponse, QARequest, QAResponseData, RetrievalTraceResponse
from app.services.agent_workflow_service import agent_workflow_service
from app.services.qa_service import qa_service
from app.services.retrieval_trace_service import retrieval_trace_service

router = APIRouter()


@router.post("/ask")
def ask_question(
    payload: QARequest,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[QAResponseData]:
    return ApiResponse(data=qa_service.answer_question(db, user_id, payload))


@router.get("/traces")
def list_traces(
    limit: int = 20,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[list[RetrievalTraceResponse]]:
    normalized_limit = min(max(limit, 1), 100)
    return ApiResponse(data=retrieval_trace_service.list_recent(db, user_id, limit=normalized_limit))


@router.get("/agent-runs")
def list_agent_runs(
    limit: int = 20,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[list[AgentRunResponse]]:
    normalized_limit = min(max(limit, 1), 100)
    runs = agent_run_repository.list_for_user(db, user_id, limit=normalized_limit)
    return ApiResponse(data=[agent_workflow_service.serialize_run(db, user_id, run) for run in runs])
