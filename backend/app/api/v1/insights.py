from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.schemas.common import ApiResponse
from app.schemas.dashboard import DashboardInsights, MemoryInsightCard
from app.services.dashboard_service import dashboard_service

router = APIRouter()
WINDOW_PATTERN = "^(default|7d|30d|90d|month|all)$"
INSIGHT_KIND_PATTERN = "^(expense|mood|learning|plan|project)$"


@router.get("/overview")
def get_insight_overview(
    window: str = Query(default="default", pattern=WINDOW_PATTERN),
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[DashboardInsights]:
    return ApiResponse(data=dashboard_service.get_insight_overview(db, user_id, window=window))


@router.get("/expenses")
def get_expense_insights(
    window: str = Query(default="default", pattern=WINDOW_PATTERN),
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[DashboardInsights]:
    return ApiResponse(data=dashboard_service.get_expense_insights(db, user_id, window=window))


@router.get("/reflection")
def get_reflection_insights(
    window: str = Query(default="default", pattern=WINDOW_PATTERN),
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[DashboardInsights]:
    return ApiResponse(data=dashboard_service.get_reflection_insights(db, user_id, window=window))


@router.get("/{kind}")
def get_insight_card(
    kind: str = Path(pattern=INSIGHT_KIND_PATTERN),
    window: str = Query(default="default", pattern=WINDOW_PATTERN),
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[MemoryInsightCard]:
    card = dashboard_service.get_insight_card(db, user_id, kind=kind, window=window)
    if card is None:
        raise HTTPException(status_code=404, detail="Insight card not found")
    return ApiResponse(data=card)
