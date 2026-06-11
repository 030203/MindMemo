from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.repos.user_repo import user_repository
from app.schemas.auth import (
    AuthResponseData,
    UserLoginRequest,
    UserProfileResponse,
    UserProfileUpdateRequest,
    UserRegisterRequest,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuthService:
    def register(self, db: Session, payload: UserRegisterRequest) -> AuthResponseData:
        email = self._normalize_email(payload.email)
        display_name = payload.display_name.strip()
        if not display_name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Display name cannot be empty")
        if len(display_name) > 64:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Display name is too long")
        if len(payload.password) < 6:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 6 characters")

        existing = user_repository.get_by_email(db, email)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

        user = user_repository.create_user(
            db,
            email=email,
            password_hash=hash_password(payload.password),
            display_name=display_name,
        )
        user_repository.create_settings(db, user.id)
        db.commit()
        db.refresh(user)
        return self._build_auth_response(str(user.id), user.display_name, user.email)

    def login(self, db: Session, payload: UserLoginRequest) -> AuthResponseData:
        user = self._resolve_login_user(db, payload.account, payload.password)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        user_repository.update_last_login(db, user, utcnow())
        db.commit()
        db.refresh(user)
        return self._build_auth_response(str(user.id), user.display_name, user.email)

    def refresh(self, db: Session, refresh_token: str) -> AuthResponseData:
        try:
            payload = decode_token(refresh_token, expected_type="refresh")
            user_id = uuid.UUID(payload["sub"])
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc

        user = user_repository.get(db, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

        return self._build_auth_response(str(user.id), user.display_name, user.email)

    def get_profile(self, user_id: str, display_name: str, email: str | None) -> UserProfileResponse:
        return UserProfileResponse(id=user_id, display_name=display_name, email=email)

    def update_profile(self, db: Session, user, payload: UserProfileUpdateRequest) -> UserProfileResponse:
        display_name = payload.display_name.strip()
        if not display_name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Display name cannot be empty")
        if len(display_name) > 64:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Display name is too long")

        if payload.email is not None:
            email = self._normalize_email(payload.email)
            existing = user_repository.get_by_email(db, email)
            if existing is not None and existing.id != user.id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

            user.email = email

        user.display_name = display_name
        db.commit()
        db.refresh(user)
        return self.get_profile(str(user.id), user.display_name, user.email)

    def _build_auth_response(self, user_id: str, display_name: str, email: str | None) -> AuthResponseData:
        access_token = create_access_token(user_id)
        refresh_token = create_refresh_token(user_id)
        return AuthResponseData(
            access_token=access_token,
            refresh_token=refresh_token,
            user_profile=UserProfileResponse(id=user_id, display_name=display_name, email=email),
        )

    def _normalize_email(self, email: str) -> str:
        normalized = email.strip().lower()
        if not normalized:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email cannot be empty")
        if len(normalized) > 255 or "@" not in normalized:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid email")
        return normalized

    def _resolve_login_user(self, db: Session, account: str, password: str):
        normalized_account = account.strip()
        if not normalized_account or not password:
            return None

        candidates = []
        seen_user_ids: set[uuid.UUID] = set()

        def add_candidate(user) -> None:
            if user is None or user.id in seen_user_ids:
                return
            seen_user_ids.add(user.id)
            candidates.append(user)

        add_candidate(user_repository.get_by_email(db, normalized_account))
        add_candidate(user_repository.get_by_phone(db, normalized_account))
        for user in user_repository.list_by_display_name(db, normalized_account):
            add_candidate(user)

        for user in candidates:
            if verify_password(password, user.password_hash):
                return user
        return None


auth_service = AuthService()
