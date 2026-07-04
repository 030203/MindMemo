from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.schemas.common import ApiResponse
from app.schemas.qa import SimpleQARequest, SimpleQAResponse
from app.services.qa_service import qa_service

router = APIRouter()


@router.post("/ask")
async def ask_question(
    payload: SimpleQARequest,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[SimpleQAResponse]:
    return ApiResponse(data=await qa_service.answer_question(db, user_id, payload))
