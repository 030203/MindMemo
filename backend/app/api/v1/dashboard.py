from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.schemas.common import ApiResponse
from app.schemas.dashboard import DashboardOverview, ReminderItem
from app.services.dashboard_service import dashboard_service, ensure_utc
from app.repos.reminder_repo import reminder_repository
from pydantic import BaseModel
from datetime import datetime
import uuid

router = APIRouter()


@router.get("/overview")
def get_overview(
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[DashboardOverview]:
    return ApiResponse(data=dashboard_service.get_overview(db, user_id))


@router.get("/reminders")
def list_reminders(
    limit: int = Query(default=5, ge=1, le=50),
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[list[ReminderItem]]:
    return ApiResponse(data=dashboard_service.list_reminders(db, user_id, limit=limit))


class ReminderUpdateRequest(BaseModel):
    due_at: datetime | None = None
    status: str | None = None


@router.patch("/reminders/{reminder_id}")
def update_reminder(
    reminder_id: str,
    payload: ReminderUpdateRequest,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse:
    try:
        rid = uuid.UUID(reminder_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="\u65e0\u6548\u7684\u63d0\u9192 ID")
    reminder = reminder_repository.get_for_user(db, user_id, rid)
    if reminder is None:
        raise HTTPException(status_code=404, detail="\u63d0\u9192\u4e0d\u5b58\u5728")
    if payload.due_at is not None:
        reminder.due_at = ensure_utc(payload.due_at)
        reminder.status = "active"
        reminder.sent_at = None
    if payload.status is not None:
        reminder.status = payload.status
    db.commit()
    return ApiResponse(data={"status": "ok"})


@router.delete("/reminders/{reminder_id}")
def delete_reminder(
    reminder_id: str,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse:
    try:
        rid = uuid.UUID(reminder_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="\u65e0\u6548\u7684\u63d0\u9192 ID")
    reminder = reminder_repository.get_for_user(db, user_id, rid)
    if reminder is None:
        raise HTTPException(status_code=404, detail="\u63d0\u9192\u4e0d\u5b58\u5728")
    reminder_repository.delete(db, reminder)
    db.commit()
    return ApiResponse(data={"status": "ok"})
