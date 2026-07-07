"""
FactExtractorTool 单元测试

测试覆盖:
  1. 简单句: "我昨天学了Python" → 1条事实
  2. 多事实: 一段话含3个知识点 → 3条事实
  3. 空文本: "" → 空列表, success=True
  4. 去重: 重复事实只保留 confidence 高的
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest


def _run(tool, **kwargs):
    return asyncio.run(tool.execute(**kwargs))


class TestFactExtractorCore:
    """核心提取逻辑测试"""

    def test_simple_sentence(self):
        """
        测试要点 1: "我昨天学了Python" → 提取 1 条事实
        """
        from app.tools.retrieval.fact_extractor import FactExtractorTool

        mock_llm = AsyncMock()
        mock_llm.parse_json.return_value = {
            "facts": [
                {
                    "subject": "用户",
                    "predicate": "学习了",
                    "object": "Python",
                    "confidence": 0.95,
                }
            ]
        }

        result = _run(
            FactExtractorTool(),
            text="我昨天学了Python",
            llm_client=mock_llm,
        )
        assert result.success is True
        assert len(result.data["facts"]) == 1
        fact = result.data["facts"][0]
        assert fact["subject"] == "用户"
        assert fact["predicate"] == "学习了"
        assert fact["object"] == "Python"

    def test_multiple_facts(self):
        """
        测试要点 2: 一段话含3个知识点 → 3条事实
        """
        from app.tools.retrieval.fact_extractor import FactExtractorTool

        mock_llm = AsyncMock()
        mock_llm.parse_json.return_value = {
            "facts": [
                {"subject": "用户", "predicate": "学习了", "object": "Python", "confidence": 0.95},
                {"subject": "用户", "predicate": "创建了", "object": "MemTodo", "confidence": 0.90},
                {"subject": "用户", "predicate": "计划学习", "object": "FastAPI", "confidence": 0.85},
            ]
        }

        result = _run(
            FactExtractorTool(),
            text="我学了Python，创建了MemTodo项目，计划本周学FastAPI",
            llm_client=mock_llm,
        )
        assert result.success is True
        assert len(result.data["facts"]) == 3

    def test_empty_text(self):
        """
        测试要点 3: 空文本 → facts=[], success=True
        """
        from app.tools.retrieval.fact_extractor import FactExtractorTool

        # 空文本不调 LLM
        result = _run(FactExtractorTool(), text="")
        assert result.success is True
        assert result.data["facts"] == []
        assert result.data["total_extracted"] == 0

    def test_no_llm_client(self):
        """缺少 llm_client → success=False"""
        from app.tools.retrieval.fact_extractor import FactExtractorTool

        result = _run(FactExtractorTool(), text="Python闭包")
        assert result.success is False
        assert "llm_client" in result.error

    def test_llm_returns_none(self):
        """LLM 解析失败 → 返回空 facts"""
        from app.tools.retrieval.fact_extractor import FactExtractorTool

        mock_llm = AsyncMock()
        mock_llm.parse_json.return_value = None

        result = _run(
            FactExtractorTool(),
            text="一些文本",
            llm_client=mock_llm,
        )
        assert result.success is True
        assert result.data["facts"] == []

    def test_max_facts_truncation(self):
        """max_facts=2 时最多返回 2 条"""
        from app.tools.retrieval.fact_extractor import FactExtractorTool

        mock_llm = AsyncMock()
        mock_llm.parse_json.return_value = {
            "facts": [
                {"subject": "S", "predicate": "P", "object": f"O{i}", "confidence": 0.9}
                for i in range(5)
            ]
        }

        result = _run(
            FactExtractorTool(),
            text="文本",
            max_facts=2,
            llm_client=mock_llm,
        )
        assert result.success is True
        assert len(result.data["facts"]) == 2

    def test_dedup_by_triple(self):
        """
        测试要点 4: 重复 (S,P,O) 只保留 confidence 最高的
        """
        from app.tools.retrieval.fact_extractor import FactExtractorTool

        mock_llm = AsyncMock()
        mock_llm.parse_json.return_value = {
            "facts": [
                {"subject": "用户", "predicate": "学习了", "object": "Python", "confidence": 0.6},
                {"subject": "用户", "predicate": "学习了", "object": "Python", "confidence": 0.95},
            ]
        }

        result = _run(
            FactExtractorTool(),
            text="文本",
            llm_client=mock_llm,
        )
        assert result.success is True
        assert len(result.data["facts"]) == 1
        assert result.data["facts"][0]["confidence"] == 0.95

    def test_llm_exception_handled(self):
        """LLM 抛异常 → success=False"""
        from app.tools.retrieval.fact_extractor import FactExtractorTool

        mock_llm = AsyncMock()
        mock_llm.parse_json.side_effect = RuntimeError("API 挂了")

        result = _run(
            FactExtractorTool(),
            text="文本",
            llm_client=mock_llm,
        )
        assert result.success is False
        assert "API 挂了" in result.error


class TestFactExtractorRegistration:
    """工具注册 + Schema"""

    def test_register(self):
        from app.tools.registry import ToolRegistry
        from app.tools.retrieval.fact_extractor import FactExtractorTool

        registry = ToolRegistry()
        registry.register(FactExtractorTool)
        tool = registry.get_tool("fact_extractor")
        assert tool is not None

    def test_schema(self):
        from app.tools.retrieval.fact_extractor import FactExtractorTool

        schema = FactExtractorTool().to_json_schema()
        assert schema["name"] == "fact_extractor"
        assert "text" in schema["parameters"]["required"]
