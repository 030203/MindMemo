import uuid

from sqlalchemy.orm import Session

from app.models.user import UserSetting
from app.repos.user_repo import user_repository
from app.schemas.settings import SettingsResponse, SettingsUpdateRequest


SUPPORTED_NOTIFY_CHANNELS = {"in_app", "pushdeer", "wecom", "serverchan"}


class SettingsService:
    def get_settings(self, db: Session, user_id: uuid.UUID) -> SettingsResponse:
        user_settings = self._ensure_settings(db, user_id)

        return SettingsResponse(
            timezone=user_settings.timezone,
            notify_channels=list(user_settings.notify_channels or []),
        )

    def update_settings(
        self,
        db: Session,
        user_id: uuid.UUID,
        payload: SettingsUpdateRequest,
    ) -> SettingsResponse:
        user_settings = self._ensure_settings(db, user_id)

        if payload.notify_channels is not None:
            user_settings.notify_channels = self._normalize_notify_channels(payload.notify_channels)

        if payload.timezone is not None:
            user_settings.timezone = payload.timezone.strip()

        db.commit()
        db.refresh(user_settings)
        return self.get_settings(db, user_id)

    def user_allows_notify_channel(self, db: Session, user_id: uuid.UUID, channel: str) -> bool:
        user_settings = user_repository.get_settings(db, user_id)
        if user_settings is None:
            return channel == "in_app"
        return channel in set(user_settings.notify_channels or [])

    def _ensure_settings(self, db: Session, user_id: uuid.UUID) -> UserSetting:
        user_settings = user_repository.get_settings(db, user_id)
        if user_settings is not None:
            return user_settings

        user_settings = user_repository.create_settings(db, user_id)
        db.commit()
        db.refresh(user_settings)
        return user_settings

    def _normalize_notify_channels(self, channels: list[str]) -> list[str]:
        normalized = []
        for channel in channels:
            if channel in SUPPORTED_NOTIFY_CHANNELS and channel not in normalized:
                normalized.append(channel)
        if "in_app" not in normalized:
            normalized.insert(0, "in_app")
        return normalized


settings_service = SettingsService()
