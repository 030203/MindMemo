import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User, UserSetting


class UserRepository:
    def get_by_email(self, db: Session, email: str) -> User | None:
        normalized = email.strip().lower()
        stmt = select(User).where(func.lower(User.email) == normalized, User.deleted_at.is_(None))
        return db.execute(stmt).scalar_one_or_none()

    def get_by_phone(self, db: Session, phone: str) -> User | None:
        normalized = phone.strip()
        stmt = select(User).where(User.phone == normalized, User.deleted_at.is_(None))
        return db.execute(stmt).scalar_one_or_none()

    def list_by_display_name(self, db: Session, display_name: str) -> list[User]:
        normalized = display_name.strip().lower()
        stmt = select(User).where(func.lower(User.display_name) == normalized, User.deleted_at.is_(None))
        return list(db.execute(stmt).scalars().all())

    def get_settings(self, db: Session, user_id: uuid.UUID) -> UserSetting | None:
        stmt = select(UserSetting).where(UserSetting.user_id == user_id)
        return db.execute(stmt).scalar_one_or_none()

    def get(self, db: Session, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
        return db.execute(stmt).scalar_one_or_none()

    def create_user(self, db: Session, *, email: str, password_hash: str, display_name: str) -> User:
        user = User(email=email, password_hash=password_hash, display_name=display_name, status="active")
        db.add(user)
        db.flush()
        return user

    def create_settings(self, db: Session, user_id: uuid.UUID) -> UserSetting:
        settings = UserSetting(
            user_id=user_id,
            timezone="Asia/Shanghai",
            language="zh-CN",
            notify_channels=["in_app"],
            llm_provider="deepseek",
            llm_model="deepseek-v4-flash",
            auto_tag_enabled=True,
            auto_summary_enabled=True,
            web_search_enabled=False,
        )
        db.add(settings)
        db.flush()
        return settings

    def update_last_login(self, db: Session, user: User, when) -> User:
        user.last_login_at = when
        db.flush()
        return user


user_repository = UserRepository()
