"""
ListTasksTool 单元测试

测试覆盖:
  1. 逾期待办进 overdue_todos，days_left 为负
  2. 未来待办进 upcoming_todos，days_left 为正
  3. 无 deadline 待办进 upcoming_todos，time_state=no_deadline
  4. 提醒只返回未来的，过去的提醒被过滤
  5. 已完成任务默认不返回，include_done=True 时返回
  6. 缺少 db/user_id → success=False
  7. 每条自带 created_at / due_at / days_left
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest


def _make_todo(**overrides):
    from app.models.todo import TodoItem

    defaults = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "title": "测试任务",
        "status": "pending",
        "priority": "medium",
        "due_at": None,
        "remind_at": None,
        "risk_level": "low",
    }
    defaults.update(overrides)
    return TodoItem(**defaults)


def _utc(days_from_now: int) -> datetime:
    """相对现在偏移 N 天的 UTC naive 时间（模拟 DB 存储）。"""
    return (datetime.now(timezone.utc) + timedelta(days=days_from_now)).replace(tzinfo=None)


def _run(tool, **kwargs):
    return asyncio.run(tool.execute(**kwargs))


class TestListTasksGrouping:
    def test_overdue_goes_to_overdue_group(self, db_session, test_user_id):
        from app.repos.todo_repo import todo_repository
        from app.tools.retrieval.list_tasks import ListTasksTool

        todo = _make_todo(user_id=test_user_id, title="创新领导力作业", due_at=_utc(-3))
        todo_repository.create(db_session, todo)

        result = _run(ListTasksTool(), db=db_session, user_id=test_user_id)

        assert result.success is True
        assert result.data["counts"]["overdue"] == 1
        entry = result.data["overdue_todos"][0]
        assert entry["title"] == "创新领导力作业"
        assert entry["time_state"] == "overdue"
        assert entry["days_left"] < 0
        assert entry["due_at"] is not None
        assert entry["created_at"] is not None

    def test_future_goes_to_upcoming(self, db_session, test_user_id):
        from app.repos.todo_repo import todo_repository
        from app.tools.retrieval.list_tasks import ListTasksTool

        todo = _make_todo(user_id=test_user_id, title="期末答辩", due_at=_utc(6))
        todo_repository.create(db_session, todo)

        result = _run(ListTasksTool(), db=db_session, user_id=test_user_id)

        assert result.data["counts"]["upcoming"] == 1
        assert result.data["counts"]["overdue"] == 0
        entry = result.data["upcoming_todos"][0]
        assert entry["time_state"] == "upcoming"
        assert entry["days_left"] > 0

    def test_no_deadline_todo_listed(self, db_session, test_user_id):
        from app.repos.todo_repo import todo_repository
        from app.tools.retrieval.list_tasks import ListTasksTool

        todo = _make_todo(user_id=test_user_id, title="读一本书", due_at=None)
        todo_repository.create(db_session, todo)

        result = _run(ListTasksTool(), db=db_session, user_id=test_user_id)

        assert result.data["counts"]["upcoming"] == 1
        entry = result.data["upcoming_todos"][0]
        assert entry["time_state"] == "no_deadline"
        assert entry["days_left"] is None


class TestReminders:
    def test_future_reminder_included_past_excluded(self, db_session, test_user_id):
        from app.repos.todo_repo import todo_repository
        from app.tools.retrieval.list_tasks import ListTasksTool

        future = _make_todo(
            user_id=test_user_id, title="明天开月会", due_at=_utc(1), remind_at=_utc(1)
        )
        past = _make_todo(
            user_id=test_user_id, title="上周的提醒", due_at=_utc(-5), remind_at=_utc(-5)
        )
        todo_repository.create(db_session, future)
        todo_repository.create(db_session, past)

        result = _run(ListTasksTool(), db=db_session, user_id=test_user_id)

        titles = [r["title"] for r in result.data["upcoming_reminders"]]
        assert "明天开月会" in titles
        assert "上周的提醒" not in titles
        # 提醒不应混进待办组
        todo_titles = [r["title"] for r in result.data["upcoming_todos"]] + [
            r["title"] for r in result.data["overdue_todos"]
        ]
        assert "明天开月会" not in todo_titles


class TestDoneFilter:
    def test_done_excluded_by_default(self, db_session, test_user_id):
        from app.repos.todo_repo import todo_repository
        from app.tools.retrieval.list_tasks import ListTasksTool

        done = _make_todo(user_id=test_user_id, title="已完成", status="done", due_at=_utc(2))
        todo_repository.create(db_session, done)

        result = _run(ListTasksTool(), db=db_session, user_id=test_user_id)
        assert result.data["counts"]["upcoming"] == 0

        result2 = _run(ListTasksTool(), db=db_session, user_id=test_user_id, include_done=True)
        assert result2.data["counts"]["upcoming"] == 1


class TestListTasksContract:
    def test_missing_context(self):
        from app.tools.retrieval.list_tasks import ListTasksTool

        result = _run(ListTasksTool())
        assert result.success is False

    def test_json_schema(self):
        from app.tools.retrieval.list_tasks import ListTasksTool

        schema = ListTasksTool().to_json_schema()
        assert schema["name"] == "list_tasks"
        # include_done 非必填
        assert "include_done" not in schema["parameters"]["required"]
