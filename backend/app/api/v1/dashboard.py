from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.schemas.common import ApiResponse
from app.schemas.dashboard import DashboardInsights, DashboardOverview, ReminderItem
from app.services.dashboard_service import dashboard_service

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


@router.get("/insights")
def get_insights(
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[DashboardInsights]:
    return ApiResponse(data=dashboard_service.get_insights(db, user_id))
