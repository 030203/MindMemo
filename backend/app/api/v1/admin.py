"""
Admin API - 管理端点

职责：
  POST /admin/run-maintenance → 手动触发 Memory Manager 维护
  GET  /admin/me              → 获取当前用户信息（含 last_maintenance_at）
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.schemas.common import ApiResponse
from app.memory.maintenance import run_maintenance
from app.models.user import User

router = APIRouter()


@router.post("/run-maintenance")
def trigger_maintenance(
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse:
    """手动触发记忆库维护（去重 + 衰减 + 过期清理）。"""
    report = run_maintenance(db, user_id=user_id)
    return ApiResponse(data=report)


@router.get("/me")
def get_admin_me(
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse:
    """获取当前用户的管理相关信息（last_maintenance_at 等）。"""
    user = db.query(User).filter(User.id == user_id).first()
    return ApiResponse(data={
        "last_maintenance_at": user.last_maintenance_at.isoformat() if user and user.last_maintenance_at else None,
    })
