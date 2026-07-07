"""
MemoryWriteTool 单元测试

测试覆盖:
  1. 完整写入: title+content+category+tags → 成功入库
  2. 自动分类: category 为空 → AI 分类 → 入库
  3. ReviewQueue触发: 低置信度 → needs_review=True
  4. 空标题: title="" → success=False
  5. 超长内容: 自动截断 + 摘要
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest


class TestMemoryWriteCore:
    """核心写入测试"""

    def test_full_create(self, db_session, test_user_id):
        """
        测试要点 1: 完整参数 → 成功入库 + 可查询
        """
        from app.repos.memory_repo import memory_repository
        from app.tools.memory.memory_write import MemoryWriteTool

        result = asyncio.run(
            MemoryWriteTool().execute(
                title="Python闭包学习笔记",
                content="闭包是函数捕获了它定义时所在作用域的变量",
                category="学习笔记",
                tags=["Python", "编程"],
                db=db_session,
                user_id=test_user_id,
            )
        )

        assert result.success is True, f"error={result.error}"
        assert result.data["action"] == "create"
        assert result.data["needs_review"] is False
        mem_id = uuid.UUID(result.data["memory_id"])

        # 验证数据库中有这条记录
        mem = memory_repository.get_for_user(db_session, test_user_id, mem_id)
        assert mem is not None
        assert mem.title == "Python闭包学习笔记"
        assert mem.created_by == "agent"

    def test_auto_classify_with_llm(self, db_session, test_user_id):
        """
        测试要点 2: category/tags 为空 → LLM 自动分类
        """
        from app.tools.memory.memory_write import MemoryWriteTool

        mock_llm = AsyncMock()
        mock_llm.parse_json.return_value = {
            "category": "学习笔记",
            "tags": ["Python", "闭包"],
            "keywords": ["闭包", "函数", "作用域"],
            "confidence": 0.90,
        }

        result = asyncio.run(
            MemoryWriteTool().execute(
                title="闭包学习",
                content="学习了Python的闭包概念",
                llm_client=mock_llm,
                db=db_session,
                user_id=test_user_id,
            )
        )

        assert result.success is True, f"error={result.error}"
        assert result.data["category"] == "学习笔记"
        assert "Python" in result.data["tags"]
        assert result.data["needs_review"] is False  # 置信度 > 0.7

    def test_low_confidence_triggers_review(self, db_session, test_user_id):
        """
        测试要点 3: 低置信度 → needs_review=True + ReviewQueue
        """
        from app.tools.memory.memory_write import MemoryWriteTool

        mock_llm = AsyncMock()
        mock_llm.parse_json.return_value = {
            "category": "其他",
            "tags": ["杂项"],
            "keywords": ["不确定"],
            "confidence": 0.45,  # < 0.7
        }

        result = asyncio.run(
            MemoryWriteTool().execute(
                title="某条模糊的笔记",
                content="内容含糊不清",
                llm_client=mock_llm,
                db=db_session,
                user_id=test_user_id,
            )
        )

        assert result.success is True, f"error={result.error}"
        assert result.data["needs_review"] is True
        assert result.data["review_id"] is not None

    def test_empty_title(self, db_session, test_user_id):
        """
        测试要点 4: 空标题 → success=False
        """
        from app.tools.memory.memory_write import MemoryWriteTool

        result = asyncio.run(
            MemoryWriteTool().execute(
                title="",
                content="有内容但没标题",
                db=db_session,
                user_id=test_user_id,
            )
        )
        assert result.success is False
        assert "title" in result.error

    def test_empty_content(self, db_session, test_user_id):
        """空内容 → success=False"""
        from app.tools.memory.memory_write import MemoryWriteTool

        result = asyncio.run(
            MemoryWriteTool().execute(
                title="有标题",
                content="",
                db=db_session,
                user_id=test_user_id,
            )
        )
        assert result.success is False
        assert "content" in result.error

    def test_long_content_truncated(self, db_session, test_user_id):
        """
        测试要点 5: 超长内容自动生成摘要
        """
        from app.tools.memory.memory_write import MemoryWriteTool

        long_text = "这是一段非常长的内容。" * 500  # ~6000 字
        result = asyncio.run(
            MemoryWriteTool().execute(
                title="长内容测试",
                content=long_text,
                category="备忘",
                tags=["测试"],
                db=db_session,
                user_id=test_user_id,
            )
        )

        assert result.success is True, f"error={result.error}"
        # 摘要应 = 200 字
        assert len(result.data["summary"]) <= 203  # 允许 "..." 截断误差

    def test_no_db_context(self):
        """缺少 db/user_id → success=False"""
        from app.tools.memory.memory_write import MemoryWriteTool

        result = asyncio.run(
            MemoryWriteTool().execute(title="测试", content="内容")
        )
        assert result.success is False
        assert "db" in result.error.lower()

    def test_update_existing(self, db_session, test_user_id):
        """更新已有记忆"""
        from app.repos.memory_repo import memory_repository
        from app.tools.memory.memory_write import MemoryWriteTool

        # 先创建一条
        from app.models.memory import MemoryItem
        mem = MemoryItem(
            id=uuid.uuid4(),
            user_id=test_user_id,
            source_type="manual",
            title="旧标题",
            content_raw="旧内容",
            category="备忘",
            tags=["旧标签"],
            keywords=[],
            entities=[],
            time_info={},
            status="active",
        )
        memory_repository.create(db_session, mem)

        result = asyncio.run(
            MemoryWriteTool().execute(
                title="新标题",
                content="新内容",
                category="学习笔记",
                tags=["Python"],
                memory_id=str(mem.id),
                db=db_session,
                user_id=test_user_id,
            )
        )

        assert result.success is True, f"error={result.error}"
        assert result.data["action"] == "update"
        assert result.data["title"] == "新标题"

    def test_update_nonexistent(self, db_session, test_user_id):
        """更新不存在的记忆 → success=False"""
        from app.tools.memory.memory_write import MemoryWriteTool

        result = asyncio.run(
            MemoryWriteTool().execute(
                title="标题",
                content="内容",
                memory_id=str(uuid.uuid4()),
                db=db_session,
                user_id=test_user_id,
            )
        )
        assert result.success is False

    def test_no_llm_fallback(self, db_session, test_user_id):
        """无 LLMClient + 无 category → fallback '备忘' + needs_review"""
        from app.tools.memory.memory_write import MemoryWriteTool

        result = asyncio.run(
            MemoryWriteTool().execute(
                title="无AI的笔记",
                content="内容",
                # 不传 category, 不传 tags, 不传 llm_client
                db=db_session,
                user_id=test_user_id,
            )
        )

        assert result.success is True, f"error={result.error}"
        assert result.data["needs_review"] is True
        assert result.data["category"] == "备忘"

    def test_timeline_event_created(self, db_session, test_user_id):
        """写入记忆后自动创建 Timeline 事件"""
        from app.tools.memory.memory_write import MemoryWriteTool

        before_count = db_session.query(
            __import__("app.models.timeline", fromlist=["TimelineEvent"]).TimelineEvent
        ).count()

        result = asyncio.run(
            MemoryWriteTool().execute(
                title="Timeline测试",
                content="验证 timeline 创建",
                category="备忘",
                tags=["测试"],
                db=db_session,
                user_id=test_user_id,
            )
        )

        assert result.success is True, f"error={result.error}"

        from app.models.timeline import TimelineEvent
        after_count = db_session.query(TimelineEvent).count()
        assert after_count > before_count


class TestMemoryWriteRegistration:
    """工具注册 + Schema"""

    def test_register(self):
        from app.tools.registry import ToolRegistry
        from app.tools.memory.memory_write import MemoryWriteTool

        registry = ToolRegistry()
        registry.register(MemoryWriteTool)
        tool = registry.get_tool("memory_write")
        assert tool is not None

    def test_schema(self):
        from app.tools.memory.memory_write import MemoryWriteTool

        schema = MemoryWriteTool().to_json_schema()
        assert schema["name"] == "memory_write"
        assert "title" in schema["parameters"]["required"]
        assert "content" in schema["parameters"]["required"]
