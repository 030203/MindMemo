"""
Pytest fixtures - 共享测试配置

提供:
- in-memory SQLite 数据库会话 (隔离测试)
- 测试用户 fixture
"""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base
from app.models.user import User


@pytest.fixture(scope="function")
def db_session() -> Session:
    """
    创建隔离的 SQLite 内存数据库会话

    每个测试函数独立，互不影响
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def test_user(db_session: Session) -> User:
    """创建测试用户"""
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        password_hash="hashed_password",
        display_name="测试用户",
        status="active",
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture(scope="function")
def test_user_id(test_user: User) -> uuid.UUID:
    """返回测试用户ID"""
    return test_user.id
