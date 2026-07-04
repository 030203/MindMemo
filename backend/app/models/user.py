import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin
from app.models.types import JSON_VARIANT


class User(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_maintenance_at: Mapped[datetime | None] = mapped_column(nullable=True)

    settings: Mapped["UserSetting"] = relationship(back_populates="user", uselist=False)
    goals: Mapped[list["Goal"]] = relationship("Goal", back_populates="user")
    insights: Mapped[list["Insight"]] = relationship("Insight", back_populates="user")


class UserSetting(Base, TimestampMixin):
    __tablename__ = "user_settings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False, unique=True, index=True
    )
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="zh-CN", nullable=False)
    quiet_hours: Mapped[dict | None] = mapped_column(JSON_VARIANT, nullable=True)
    notify_channels: Mapped[list | None] = mapped_column(JSON_VARIANT, nullable=True)
    # DB still has these columns; kept for compatibility, no longer used in app logic
    llm_provider: Mapped[str] = mapped_column("llm_provider", String(32), default="deepseek", nullable=False)
    llm_model: Mapped[str] = mapped_column("llm_model", String(64), default="deepseek-chat", nullable=False)

    user: Mapped[User] = relationship(back_populates="settings")
