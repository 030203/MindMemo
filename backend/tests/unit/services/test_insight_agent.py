"""
Insight Agent 单元测试

测试要点（对齐 insight_agent_service.py）：
  1. 有数据: 插入 5 条记忆 → 生成洞察 → insights 表有记录
  2. 无数据: 记忆 0 条 → skipped
  3. LLM 不可用: 记忆 ≥3 条但 LLM 挂 → 跳过 LLM，返回 stats
  4. 数据太少: 1 条记忆 → 跳过 LLM，返回 stats
  5. LLM 返回无效 → 跳过
  6. LLM 抛出异常 → 跳过
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base
from app.models.user import User
from app.models.memory import MemoryItem
from app.services.insight_agent_service import InsightAgent


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


def _make_memories(db, uid, count=5):
    now = datetime.now(timezone.utc)
    for i in range(count):
        m = MemoryItem(
            id=uuid.uuid4(), user_id=uid, source_type="manual",
            title=f"测试{i}", content_raw=f"内容{i}",
            category="学习笔记", tags=["测试"], keywords=[],
            importance_score=0.5, created_at=now, updated_at=now,
        )
        db.add(m)
    db.commit()


def _make_llm(insight_type="weekly", title="测试洞察", content="你最近主要学习了Python。", confidence=0.8):
    return MagicMock(return_value={"insight_type": insight_type, "title": title, "content": content, "confidence": confidence})

def _make_llm_none():
    return MagicMock(return_value=None)

def _make_llm_raise():
    return MagicMock(side_effect=RuntimeError("LLM挂"))


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestInsightAgent:
    def test_with_data(self):
        db, uid = _setup()
        _make_memories(db, uid, 5)
        agent = InsightAgent(llm_parse_json=_make_llm())
        result = run(agent.generate_insight(db, uid))
        db.close()
        assert result["success"] is True
        assert "insight_id" in result

    def test_no_data(self):
        db, uid = _setup()
        agent = InsightAgent(llm_parse_json=_make_llm())
        result = run(agent.generate_insight(db, uid))
        db.close()
        assert result["success"] is True
        assert result.get("skipped") is True

    def test_too_few_data(self):
        db, uid = _setup()
        _make_memories(db, uid, 1)
        called = []
        def spy(**kw):
            called.append(True)
            return _make_llm()()
        agent = InsightAgent(llm_parse_json=spy)
        result = run(agent.generate_insight(db, uid))
        db.close()
        assert result["success"] is True
        assert result.get("skipped") is True
        assert len(called) == 0
        assert "stats" in result

    def test_llm_unavailable(self):
        db, uid = _setup()
        _make_memories(db, uid, 3)
        agent = InsightAgent(llm_parse_json=_make_llm_none())
        result = run(agent.generate_insight(db, uid))
        db.close()
        assert result["success"] is True
        assert result.get("skipped") is True

    def test_llm_raises(self):
        db, uid = _setup()
        _make_memories(db, uid, 3)
        agent = InsightAgent(llm_parse_json=_make_llm_raise())
        result = run(agent.generate_insight(db, uid))
        db.close()
        assert result["success"] is True
        assert result.get("skipped") is True

    def test_multiple_categories(self):
        db, uid = _setup()
        now = datetime.now(timezone.utc)
        for i, cat in enumerate(["学习笔记", "生活", "学习笔记", "工作", "生活"]):
            db.add(MemoryItem(id=uuid.uuid4(), user_id=uid, source_type="manual",
                              title=f"m{i}", content_raw=f"c{i}", category=cat, tags=["tag"],
                              keywords=[], importance_score=0.5, created_at=now, updated_at=now))
        db.commit()
        agent = InsightAgent(llm_parse_json=_make_llm(title="多类别分析", content="多类别内容"))
        result = run(agent.generate_insight(db, uid))
        db.close()
        assert result["success"] is True
        assert "insight_id" in result
