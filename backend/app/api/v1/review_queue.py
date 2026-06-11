from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.schemas.common import ApiResponse
from app.schemas.review import ReviewDecisionRequest, ReviewQueueItemResponse
from app.services.review_service import review_service

router = APIRouter()


@router.get("")
def list_review_queue(
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[list[ReviewQueueItemResponse]]:
    return ApiResponse(data=review_service.list_reviews(db, user_id))


@router.post("/{review_id}/confirm")
def confirm_review(
    review_id: str,
    payload: ReviewDecisionRequest | None = None,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[ReviewQueueItemResponse]:
    item = review_service.confirm_review(db, user_id, review_id, note=payload.note if payload else "")
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return ApiResponse(data=item)


@router.post("/{review_id}/ignore")
def ignore_review(
    review_id: str,
    payload: ReviewDecisionRequest | None = None,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[ReviewQueueItemResponse]:
    item = review_service.ignore_review(db, user_id, review_id, note=payload.note if payload else "")
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return ApiResponse(data=item)


@router.post("/{review_id}/convert-to-todo")
def convert_review_to_todo(
    review_id: str,
    payload: ReviewDecisionRequest | None = None,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[ReviewQueueItemResponse]:
    item = review_service.convert_to_todo(db, user_id, review_id, note=payload.note if payload else "")
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    return ApiResponse(data=item)
