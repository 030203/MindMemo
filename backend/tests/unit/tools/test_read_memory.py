"""
ReadMemoryTool 单元测试

测试覆盖:
  1. 正常读取: 返回完整 content_raw
  2. ID 不存在 / 非本人: success=False
  3. 非法 UUID: success=False，不抛异常
  4. 缺少 db/user_id 上下文: success=False
  5. 超长正文截断: content_truncated=True
"""
from __future__ import annotations

import asyncio
import uuid

import pytest


def _make_memory(**overrides):
    from app.models.memory import MemoryItem

    defaults = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "source_type": "pdf",
        "title": "测试简历",
        "content_raw": "姓名：黎涛\n项目经历：搭建了 RAG 检索系统，使用 pgvector 做向量召回。",
        "content_clean": None,
        "content_summary": "简历摘要",
        "category": "learning",
        "tags": ["RAG"],
        "keywords": ["pgvector"],
        "entities": [],
        "time_info": {"file_name": "resume.pdf"},
        "importance_score": 0.8,
        "status": "active",
    }
    defaults.update(overrides)
    return MemoryItem(**defaults)


class TestReadMemoryCore:
    def test_read_full_content(self, db_session, test_user_id):
        """正常读取 → 返回完整 content_raw 而非摘要"""
        from app.repos.memory_repo import memory_repository
        from app.tools.retrieval.read_memory import ReadMemoryTool

        full_text = "姓名：黎涛\n项目：RAG 检索系统。技能：Agent、pgvector、长期记忆。"
        m = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            content_raw=full_text,
            content_summary="只是摘要",
        )
        memory_repository.create(db_session, m)

        tool = ReadMemoryTool()
        result = asyncio.run(
            tool.execute(memory_id=str(m.id), db=db_session, user_id=test_user_id)
        )

        assert result.success is True
        assert result.data["content"] == full_text
        assert result.data["content"] != result.data.get("summary")
        assert result.data["file_name"] == "resume.pdf"
        assert result.data["content_truncated"] is False

    def test_not_found(self, db_session, test_user_id):
        """随机 ID → success=False"""
        from app.tools.retrieval.read_memory import ReadMemoryTool

        tool = ReadMemoryTool()
        result = asyncio.run(
            tool.execute(memory_id=str(uuid.uuid4()), db=db_session, user_id=test_user_id)
        )
        assert result.success is False

    def test_other_user_denied(self, db_session, test_user_id):
        """他人记忆 → 归属校验失败，success=False"""
        from app.repos.memory_repo import memory_repository
        from app.tools.retrieval.read_memory import ReadMemoryTool

        other_user = uuid.uuid4()
        m = _make_memory(id=uuid.uuid4(), user_id=other_user)
        memory_repository.create(db_session, m)

        tool = ReadMemoryTool()
        result = asyncio.run(
            tool.execute(memory_id=str(m.id), db=db_session, user_id=test_user_id)
        )
        assert result.success is False

    def test_invalid_uuid(self, db_session, test_user_id):
        """非法 UUID → success=False，不抛异常"""
        from app.tools.retrieval.read_memory import ReadMemoryTool

        tool = ReadMemoryTool()
        result = asyncio.run(
            tool.execute(memory_id="not-a-uuid", db=db_session, user_id=test_user_id)
        )
        assert result.success is False
        assert "memory_id" in result.error

    def test_missing_context(self):
        """不传 db/user_id → success=False"""
        from app.tools.retrieval.read_memory import ReadMemoryTool

        tool = ReadMemoryTool()
        result = asyncio.run(tool.execute(memory_id=str(uuid.uuid4())))
        assert result.success is False

    def test_long_content_truncated(self, db_session, test_user_id):
        """超长正文 → 截断并标记 content_truncated=True"""
        from app.repos.memory_repo import memory_repository
        from app.tools.retrieval.read_memory import ReadMemoryTool

        long_text = "字" * 20000
        m = _make_memory(id=uuid.uuid4(), user_id=test_user_id, content_raw=long_text)
        memory_repository.create(db_session, m)

        tool = ReadMemoryTool()
        result = asyncio.run(
            tool.execute(memory_id=str(m.id), db=db_session, user_id=test_user_id)
        )
        assert result.success is True
        assert result.data["content_truncated"] is True
        assert len(result.data["content"]) < len(long_text)


class TestReadMemoryRegistration:
    def test_json_schema(self):
        """Schema 符合 OpenAI Function Calling 规范"""
        from app.tools.retrieval.read_memory import ReadMemoryTool

        schema = ReadMemoryTool().to_json_schema()
        assert schema["name"] == "read_memory"
        assert "memory_id" in schema["parameters"]["required"]
