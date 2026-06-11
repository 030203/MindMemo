from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.schemas.common import ApiResponse
from app.schemas.settings import (
    NotificationProviderStatus,
    NotificationTestRequest,
    NotificationTestResponse,
    SettingsResponse,
    SettingsUpdateRequest,
)
from app.services.notification_service import reminder_notification_service
from app.services.settings_service import settings_service

router = APIRouter()


@router.get("")
def get_settings(
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[SettingsResponse]:
    return ApiResponse(data=settings_service.get_settings(db, user_id))


@router.patch("")
def update_settings(
    payload: SettingsUpdateRequest,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[SettingsResponse]:
    return ApiResponse(data=settings_service.update_settings(db, user_id, payload))


@router.get("/notification-providers")
def list_notification_providers(
    user_id=Depends(get_current_user_id),
) -> ApiResponse[list[NotificationProviderStatus]]:
    _ = user_id
    return ApiResponse(data=reminder_notification_service.provider_statuses())


@router.post("/notifications/test")
def test_notification(
    payload: NotificationTestRequest,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[NotificationTestResponse]:
    if not settings_service.user_allows_notify_channel(db, user_id, payload.channel):
        raise HTTPException(status_code=400, detail="Notification channel is not enabled for this user")

    sent = reminder_notification_service.send_test(payload.channel)
    if not sent:
        raise HTTPException(status_code=400, detail="Notification provider is not configured or test send failed")

    return ApiResponse(data=NotificationTestResponse(channel=payload.channel, sent=sent))
