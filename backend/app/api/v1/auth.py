from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.schemas.auth import (
    AuthResponseData,
    RefreshTokenRequest,
    UserLoginRequest,
    UserProfileResponse,
    UserProfileUpdateRequest,
    UserRegisterRequest,
)
from app.schemas.common import ApiResponse
from app.services.auth_service import auth_service

router = APIRouter()


@router.post("/register")
def register(
    payload: UserRegisterRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[AuthResponseData]:
    return ApiResponse(data=auth_service.register(db, payload))


@router.post("/login")
def login(
    payload: UserLoginRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[AuthResponseData]:
    return ApiResponse(data=auth_service.login(db, payload))


@router.post("/refresh")
def refresh(
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
) -> ApiResponse[AuthResponseData]:
    return ApiResponse(data=auth_service.refresh(db, payload.refresh_token))


@router.get("/me")
def me(user=Depends(get_current_user)) -> ApiResponse[UserProfileResponse]:
    return ApiResponse(
        data=UserProfileResponse(
            id=str(user.id),
            display_name=user.display_name,
            email=user.email,
        )
    )


@router.patch("/me")
def update_me(
    payload: UserProfileUpdateRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
) -> ApiResponse[UserProfileResponse]:
    return ApiResponse(data=auth_service.update_profile(db, user, payload))
