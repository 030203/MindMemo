"""
Memory Manager Maintenance 单元测试

测试要点:
  1. 去重: 插入2条相似标题的记忆 → ReviewQueue 增加
  2. 去重: 不相似的记忆 → 不触发 ReviewQueue
  3. 衰减: last_recalled_at 半年 → importance_score 降低
  4. 衰减: 近期访问 → importance_score 不变
  5. 空库: 无记忆 → 不崩溃
  6. 过期 Insights 清理
  7. 指定用户执行
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base
from app.models.user import User
from app.models.memory import MemoryItem
from app.models.insight import Insight
from app.models.review import ReviewQueueItem
from app.memory.maintenance import run_maintenance, _jaccard_similarity, _dedup, _decay


def _setup() -> tuple[Session, uuid.UUID]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    user = User(id=uuid.uuid4(), email="t@t.com", password_hash="h", display_name="t", status="active")
    db.add(user)
    db.commit()
    db.refresh(user)
    return db, user.id


def _make_memory(db, uid, title, importance=0.8, days_ago=None):
    now = datetime.now(timezone.utc)
    created = now - (timedelta(days=days_ago) if days_ago else timedelta(days=1))
    m = MemoryItem(
        id=uuid.uuid4(), user_id=uid, source_type="manual",
        title=title, content_raw="x" * 100,
        category="笔记", tags=["测试"], keywords=[],
        importance_score=importance, created_at=created, updated_at=now,
    )
    if days_ago is not None:
        m.last_recalled_at = now - timedelta(days=days_ago)
    db.add(m)
    db.commit()
    return m


class TestMaintenance:
    def test_dedup_finds_duplicates(self):
        db, uid = _setup()
        _make_memory(db, uid, "今天学习了Python闭包")
        _make_memory(db, uid, "今天学习了Python闭包的知识")
        report = run_maintenance(db, uid)
        assert report["duplicates_found"] >= 1
        db.close()

    def test_dedup_ignores_distinct(self):
        db, uid = _setup()
        _make_memory(db, uid, "今天学习了Python闭包")
        _make_memory(db, uid, "明天要去爬山")
        report = run_maintenance(db, uid)
        assert report["duplicates_found"] == 0
        db.close()

    def test_decay_old_memories(self):
        db, uid = _setup()
        m = _make_memory(db, uid, "旧记忆", importance=0.9, days_ago=200)
        report = run_maintenance(db, uid)
        db.refresh(m)
        assert m.importance_score < 0.9
        assert m.importance_score > 0  # 衰减了但没归零
        assert report["decayed_memories"] >= 1
        db.close()

    def test_decay_recent_memory_unaffected(self):
        db, uid = _setup()
        m = _make_memory(db, uid, "新记忆", importance=0.9, days_ago=10)
        report = run_maintenance(db, uid)
        db.refresh(m)
        assert m.importance_score == 0.9
        assert report["decayed_memories"] == 0
        db.close()

    def test_dedup_creates_review_queue_item(self):
        db, uid = _setup()
        _make_memory(db, uid, "今天学习了Python闭包")
        _make_memory(db, uid, "今天学习了Python闭包的知识")
        run_maintenance(db, uid)
        items = db.query(ReviewQueueItem).filter(ReviewQueueItem.user_id == uid).all()
        assert len(items) >= 1
        assert items[0].review_type == "duplicate_detection"
        assert items[0].status == "pending"
        db.close()

    def test_cleanup_expired_insights(self):
        db, uid = _setup()
        now = datetime.now(timezone.utc)
        expired = Insight(user_id=uid, insight_type="weekly", title="旧", content="旧",
                          expires_at=now - timedelta(days=1))
        active = Insight(user_id=uid, insight_type="weekly", title="新", content="新",
                         expires_at=now + timedelta(days=7))
        db.add_all([expired, active])
        db.commit()
        report = run_maintenance(db, uid)
        assert report["expired_insights"] >= 1
        remaining = db.query(Insight).all()
        assert len(remaining) == 1
        assert remaining[0].title == "新"
        db.close()

    def test_empty_db(self):
        db, uid = _setup()
        report = run_maintenance(db, uid)
        assert report["duplicates_found"] == 0
        assert report["decayed_memories"] == 0
        db.close()

    def test_jaccard_similarity(self):
        assert _jaccard_similarity("abc", "abc") == 1.0
        assert _jaccard_similarity("abc", "def") == 0.0
        assert 0 < _jaccard_similarity("今天学了Python", "今天学了Python闭包") < 1
