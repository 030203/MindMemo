"""
Insights API - 洞察管理端点

职责：
  POST /insights/generate → 手动触发 Insight Agent 生成最近洞察
  GET  /insights          → 读取已生成的洞察列表
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.schemas.common import ApiResponse
from app.services.insight_agent_service import insight_agent
from app.repos.insight_repo import insight_repository

router = APIRouter()


@router.post("/generate")
async def generate_insight(
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse:
    """手动触发 Insight Agent 生成最近 7 天的洞察。"""
    result = await insight_agent.generate_insight(
        db=db,
        user_id=user_id,
        days=7,
    )
    return ApiResponse(data=result)


@router.get("/")
def list_insights(
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
    days: int = 7,
) -> ApiResponse:
    """读取最近 N 天的洞察列表。"""
    insights = insight_repository.get_recent(db, user_id, days=days)
    return ApiResponse(data=[
        {
            "id": str(i.id),
            "insight_type": i.insight_type,
            "title": i.title,
            "content": i.content,
            "confidence": i.confidence_score,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in insights
    ])
