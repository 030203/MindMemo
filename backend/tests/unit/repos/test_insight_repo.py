"""
InsightRepository 单元测试

测试内容:
1. 洞察 CRUD 操作
2. 按时间/类型查询
3. 过期清理
4. 边界条件
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.repos.insight_repo import insight_repository, InsightRepository


# ============ 洞察 CRUD 测试 ============


def test_create_insight(db_session: Session, test_user_id: uuid.UUID):
    """测试创建洞察"""
    insight = insight_repository.create(
        db_session,
        user_id=test_user_id,
        insight_type="pattern",
        title="每日习惯模式",
        content="用户每天早上8点记录日记",
        data={"time": "08:00", "action": "diary"},
        confidence_score=0.85,
    )

    assert insight.id is not None
    assert insight.insight_type == "pattern"
    assert insight.title == "每日习惯模式"
    assert insight.content == "用户每天早上8点记录日记"
    assert insight.data == {"time": "08:00", "action": "diary"}
    assert insight.confidence_score == 0.85
    assert insight.user_id == test_user_id


def test_create_insight_with_expiry(db_session: Session, test_user_id: uuid.UUID):
    """测试创建带过期时间的洞察"""
    from datetime import timedelta as td
    expires = datetime.now(timezone.utc) + timedelta(days=7)

    insight = insight_repository.create(
        db_session,
        user_id=test_user_id,
        insight_type="report",
        title="周报",
        content="本周总结",
        expires_at=expires,
    )

    assert insight.expires_at is not None
    # SQLite does not preserve timezone; compare timestamps instead
    expected_ts = expires.timestamp()
    actual_ts = insight.expires_at.replace(tzinfo=timezone.utc).timestamp() if insight.expires_at.tzinfo is None else insight.expires_at.timestamp()
    assert abs(actual_ts - expected_ts) < 5  # within 5 seconds


def test_get_recent(db_session: Session, test_user_id: uuid.UUID):
    """测试获取最近的洞察"""
    # 创建3条洞察
    for i in range(3):
        insight_repository.create(
            db_session,
            user_id=test_user_id,
            insight_type="pattern",
            title=f"洞察{i+1}",
            content=f"内容{i+1}",
        )

    recent = insight_repository.get_recent(
        db_session, test_user_id, days=7, limit=10
    )
    assert len(recent) == 3
    # 按创建时间倒序（最后插入的最晚，排最前）
    titles = [r.title for r in recent]
    assert titles == ["洞察3", "洞察2", "洞察1"]


def test_get_recent_limit(db_session: Session, test_user_id: uuid.UUID):
    """测试获取最近洞察的数量限制"""
    for i in range(5):
        insight_repository.create(
            db_session,
            user_id=test_user_id,
            insight_type="pattern",
            title=f"洞察{i+1}",
            content=f"内容{i+1}",
        )

    recent = insight_repository.get_recent(
        db_session, test_user_id, days=7, limit=3
    )
    assert len(recent) == 3


def test_get_by_type(db_session: Session, test_user_id: uuid.UUID):
    """测试按类型获取洞察"""
    insight_repository.create(
        db_session, user_id=test_user_id,
        insight_type="pattern", title="模式1", content="c",
    )
    insight_repository.create(
        db_session, user_id=test_user_id,
        insight_type="pattern", title="模式2", content="c",
    )
    insight_repository.create(
        db_session, user_id=test_user_id,
        insight_type="report", title="报告1", content="c",
    )

    patterns = insight_repository.get_by_type(
        db_session, test_user_id, "pattern"
    )
    assert len(patterns) == 2

    reports = insight_repository.get_by_type(
        db_session, test_user_id, "report"
    )
    assert len(reports) == 1

    # 不存在的类型
    empty = insight_repository.get_by_type(
        db_session, test_user_id, "nonexistent"
    )
    assert len(empty) == 0


def test_get_by_id(db_session: Session, test_user_id: uuid.UUID):
    """测试根据 ID 获取洞察"""
    insight = insight_repository.create(
        db_session, user_id=test_user_id,
        insight_type="pattern", title="测试", content="内容",
    )

    retrieved = insight_repository.get_by_id(
        db_session, insight.id, test_user_id
    )
    assert retrieved is not None
    assert retrieved.title == "测试"

    # 用户隔离
    not_found = insight_repository.get_by_id(
        db_session, insight.id, uuid.uuid4()
    )
    assert not_found is None


# ============ 清理测试 ============


def test_delete_expired(db_session: Session, test_user_id: uuid.UUID):
    """测试删除过期洞察"""
    past = datetime.now(timezone.utc) - timedelta(days=1)
    future = datetime.now(timezone.utc) + timedelta(days=1)

    # 创建已过期的洞察
    insight_repository.create(
        db_session, user_id=test_user_id,
        insight_type="pattern", title="过期洞察", content="c",
        expires_at=past,
    )
    # 创建未过期的洞察
    insight_repository.create(
        db_session, user_id=test_user_id,
        insight_type="pattern", title="有效洞察", content="c",
        expires_at=future,
    )
    # 创建无过期时间的洞察
    insight_repository.create(
        db_session, user_id=test_user_id,
        insight_type="pattern", title="永久洞察", content="c",
    )

    deleted = insight_repository.delete_expired(db_session)
    assert deleted == 1

    # 确认只有过期的那条被删除
    remaining = insight_repository.get_recent(
        db_session, test_user_id, days=30, limit=10
    )
    assert len(remaining) == 2
    titles = {i.title for i in remaining}
    assert "过期洞察" not in titles
    assert "有效洞察" in titles
    assert "永久洞察" in titles


def test_delete_for_user(db_session: Session, test_user_id: uuid.UUID):
    """测试删除用户的洞察"""
    insight = insight_repository.create(
        db_session, user_id=test_user_id,
        insight_type="pattern", title="待删除", content="c",
    )

    result = insight_repository.delete_for_user(
        db_session, test_user_id, insight.id
    )
    assert result is True

    # 确认已删除
    retrieved = insight_repository.get_by_id(
        db_session, insight.id, test_user_id
    )
    assert retrieved is None


def test_delete_for_user_not_found(db_session: Session, test_user_id: uuid.UUID):
    """测试删除不存在的洞察"""
    result = insight_repository.delete_for_user(
        db_session, test_user_id, uuid.uuid4()
    )
    assert result is False


def test_delete_for_user_wrong_user(db_session: Session, test_user_id: uuid.UUID):
    """测试其他用户不能删除"""
    insight = insight_repository.create(
        db_session, user_id=test_user_id,
        insight_type="pattern", title="保护", content="c",
    )

    # 其他用户尝试删除
    result = insight_repository.delete_for_user(
        db_session, uuid.uuid4(), insight.id
    )
    assert result is False

    # 原用户的洞察还在
    retrieved = insight_repository.get_by_id(
        db_session, insight.id, test_user_id
    )
    assert retrieved is not None


# ============ 多样化类型测试 ============


def test_multiple_insight_types(db_session: Session, test_user_id: uuid.UUID):
    """测试多种洞察类型"""
    types = ["pattern", "cluster", "report", "expense", "reflection", "learning", "project"]

    for t in types:
        insight_repository.create(
            db_session, user_id=test_user_id,
            insight_type=t, title=f"{t}_洞察", content=f"{t}_内容",
        )

    for t in types:
        results = insight_repository.get_by_type(db_session, test_user_id, t)
        assert len(results) == 1
        assert results[0].insight_type == t


def test_confidence_score_range(db_session: Session, test_user_id: uuid.UUID):
    """测试置信度评分"""
    insight = insight_repository.create(
        db_session, user_id=test_user_id,
        insight_type="pattern", title="高置信度", content="c",
        confidence_score=0.95,
    )
    assert insight.confidence_score == 0.95

    insight2 = insight_repository.create(
        db_session, user_id=test_user_id,
        insight_type="pattern", title="低置信度", content="c",
        confidence_score=0.0,
    )
    assert insight2.confidence_score == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
