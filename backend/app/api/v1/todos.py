from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.schemas.common import ApiResponse
from app.schemas.todo import TodoCreateRequest, TodoResponse, TodoUpdateRequest
from app.services.todo_service import todo_service

router = APIRouter()


@router.get("")
def list_todos(
    q: str | None = Query(default=None, description="Free-text search over todo title and description"),
    status: str | None = Query(default=None, description="Todo status filter"),
    priority: str | None = Query(default=None, description="Todo priority filter"),
    sort: str | None = Query(default="priority", description="Sort mode: priority, newest, due"),
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[list[TodoResponse]]:
    return ApiResponse(data=todo_service.list_todos(db, user_id, query_text=q, status=status, priority=priority, sort=sort))


@router.post("")
def create_todo(
    payload: TodoCreateRequest,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[TodoResponse]:
    return ApiResponse(data=todo_service.create_todo(db, user_id, payload))


@router.post("/{todo_id}/complete")
def complete_todo(
    todo_id: str,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[TodoResponse]:
    todo = todo_service.complete_todo(db, user_id, todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    return ApiResponse(data=todo)


@router.patch("/{todo_id}")
def update_todo(
    todo_id: str,
    payload: TodoUpdateRequest,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[TodoResponse]:
    todo = todo_service.update_todo(db, user_id, todo_id, payload)
    if todo is None:
        raise HTTPException(status_code=404, detail="Todo not found")
    return ApiResponse(data=todo)


@router.delete("/{todo_id}")
def delete_todo(
    todo_id: str,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[dict]:
    deleted = todo_service.delete_todo(db, user_id, todo_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Todo not found")
    return ApiResponse(data={"deleted": True})
