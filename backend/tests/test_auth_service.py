from __future__ import annotations

from pathlib import Path
import sys
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.security import hash_password  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.auth import UserLoginRequest, UserRegisterRequest  # noqa: E402
from app.services.auth_service import auth_service  # noqa: E402


class AuthServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        self.db = self.SessionLocal()

    def tearDown(self) -> None:
        self.db.close()

    def _create_user(self, *, email: str, display_name: str, password: str, phone: str | None = None) -> User:
        user = User(
            email=email,
            phone=phone,
            password_hash=hash_password(password),
            display_name=display_name,
            status="active",
        )
        self.db.add(user)
        self.db.flush()
        return user

    def test_login_supports_duplicate_display_name_with_password_match(self) -> None:
        self._create_user(email="first@example.com", display_name="Proxiamo", password="first-pass")
        expected = self._create_user(email="second@example.com", display_name="Proxiamo", password="second-pass")
        self.db.commit()

        response = auth_service.login(
            self.db,
            UserLoginRequest(account="Proxiamo", password="second-pass"),
        )

        self.assertEqual(response.user_profile.id, str(expected.id))
        self.assertEqual(response.user_profile.email, "second@example.com")

    def test_login_supports_phone_account(self) -> None:
        expected = self._create_user(
            email="phone@example.com",
            display_name="Phone Login",
            password="phone-pass",
            phone="13800138000",
        )
        self.db.commit()

        response = auth_service.login(
            self.db,
            UserLoginRequest(account="13800138000", password="phone-pass"),
        )

        self.assertEqual(response.user_profile.id, str(expected.id))
        self.assertEqual(response.user_profile.email, "phone@example.com")

    def test_register_rejects_invalid_email(self) -> None:
        with self.assertRaises(HTTPException) as context:
            auth_service.register(
                self.db,
                UserRegisterRequest(
                    email="456456",
                    password="secret123",
                    display_name="Broken Email",
                ),
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertEqual(context.exception.detail, "Invalid email")


if __name__ == "__main__":
    unittest.main()
