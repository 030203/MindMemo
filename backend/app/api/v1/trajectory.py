"""
Trajectory API - Agent 执行轨迹查询

职责：
  GET /trajectory/{session_id} → 查看某次 Agent 执行的完整推理轨迹
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.models.agent_run import AgentRun
from app.schemas.common import ApiResponse

router = APIRouter()


@router.get("/{session_id}")
def get_trajectory(
    session_id: str,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse:
    """查看指定 session 的 Agent 执行轨迹。"""
    run = (
        db.query(AgentRun)
        .filter(
            AgentRun.session_id == session_id,
            AgentRun.user_id == user_id,
        )
        .first()
    )
    if not run:
        return ApiResponse(data=None, code=404, message="未找到该执行记录")

    return ApiResponse(data={
        "id": str(run.id),
        "session_id": run.session_id,
        "agent_name": run.agent_name,
        "question": run.question,
        "answer": run.answer,
        "trajectory": run.trajectory or [],
        "tool_calls": run.tool_calls or [],
        "duration_ms": run.duration_ms,
        "status": run.status,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    })
