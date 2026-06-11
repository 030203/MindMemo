from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.schemas.common import ApiResponse
from app.schemas.memory import MemoryCreateRequest, MemoryDetail, MemoryListItem, MemoryRelatedItem, MemoryUpdateRequest
from app.services.memory_relation_service import memory_relation_service
from app.services.memory_service import memory_service

router = APIRouter()


@router.get("")
def list_memories(
    q: str | None = Query(default=None, description="Free-text search over memory title and content"),
    category: str | None = Query(default=None, description="Memory category filter"),
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[list[MemoryListItem]]:
    return ApiResponse(data=memory_service.list_memories(db, user_id, query_text=q, category=category))


@router.post("")
def create_memory(
    payload: MemoryCreateRequest,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[MemoryDetail]:
    return ApiResponse(data=memory_service.create_memory(db, user_id, payload))


@router.get("/{memory_id}")
def get_memory(
    memory_id: str,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[MemoryDetail]:
    memory = memory_service.get_memory(db, user_id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return ApiResponse(data=memory)


@router.get("/{memory_id}/related")
def list_related_memories(
    memory_id: str,
    limit: int = Query(default=8, ge=1, le=20),
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[list[MemoryRelatedItem]]:
    memory = memory_service.get_memory(db, user_id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return ApiResponse(data=memory_relation_service.list_related(db, user_id, memory_id, limit=limit))


@router.post("/{memory_id}/relations/rebuild")
def rebuild_memory_relations(
    memory_id: str,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[list[MemoryRelatedItem]]:
    memory = memory_service.get_memory_model(db, user_id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    memory_relation_service.rebuild_for_memory(db, user_id, memory)
    db.commit()
    return ApiResponse(data=memory_relation_service.list_related(db, user_id, memory_id))


@router.patch("/{memory_id}")
def update_memory(
    memory_id: str,
    payload: MemoryUpdateRequest,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[MemoryDetail]:
    memory = memory_service.update_memory(db, user_id, memory_id, payload)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return ApiResponse(data=memory)


@router.delete("/{memory_id}")
def delete_memory(
    memory_id: str,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[dict[str, bool]]:
    deleted = memory_service.delete_memory(db, user_id, memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return ApiResponse(data={"deleted": True})
