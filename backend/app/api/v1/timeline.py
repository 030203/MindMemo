from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.schemas.common import ApiResponse
from app.schemas.timeline import MemorySignalResponse, TimelineEventResponse
from app.services.timeline_service import timeline_service

router = APIRouter()


@router.get("")
def list_timeline(
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[list[TimelineEventResponse]]:
    return ApiResponse(data=timeline_service.list_timeline(db, user_id))


@router.get("/signals")
def list_memory_signals(
    fact_type: str | None = None,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[list[MemorySignalResponse]]:
    return ApiResponse(data=timeline_service.list_memory_signals(db, user_id, fact_type=fact_type))
