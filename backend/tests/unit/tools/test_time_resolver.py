"""
TimeResolverTool 单元测试

测试覆盖:
  1. "今天" → 正确日期范围
  2. "上周" → 周一~周日
  3. "最近3天" → 3天前~今天
  4. "去年三月" → LLM兜底, confidence < 1.0
  5. 非法输入: "香蕉" → success=False
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta

import pytest


def _run(tool, **kwargs):
    return asyncio.run(tool.execute(**kwargs))


class TestTimeResolverRules:
    """规则解析器测试 —— 不调 LLM"""

    def test_today(self):
        """测试要点 1: '今天' → 今天 00:00 ~ 23:59"""
        from app.tools.retrieval.time_resolver import TimeResolverTool

        result = _run(TimeResolverTool(), time_expression="今天")
        assert result.success is True
        today_iso = date.today().isoformat()
        assert result.data["start"].startswith(today_iso)
        assert result.data["end"].startswith(today_iso)
        assert result.data["confidence"] == 1.0
        assert result.data["resolution_method"] == "rule"

    def test_yesterday(self):
        """'昨天' → 昨天 00:00 ~ 23:59"""
        from app.tools.retrieval.time_resolver import TimeResolverTool

        result = _run(TimeResolverTool(), time_expression="昨天")
        assert result.success is True
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        assert result.data["start"].startswith(yesterday)

    def test_tomorrow(self):
        """'明天' → 明天 00:00 ~ 23:59"""
        from app.tools.retrieval.time_resolver import TimeResolverTool

        result = _run(TimeResolverTool(), time_expression="明天")
        assert result.success is True
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        assert result.data["start"].startswith(tomorrow)

    def test_last_week(self):
        """测试要点 2: '上周' → 上周一 ~ 上周日"""
        from app.tools.retrieval.time_resolver import TimeResolverTool

        result = _run(TimeResolverTool(), time_expression="上周")
        assert result.success is True
        # 验证 start < end 且间隔 <= 7 天
        start = datetime.fromisoformat(result.data["start"])
        end = datetime.fromisoformat(result.data["end"])
        delta = (end - start).days
        assert 6 <= delta <= 7, f"上周范围应为 6~7 天，实际 {delta} 天"
        # start 应该在今天之前
        assert start.date() < date.today()

    def test_this_week(self):
        """'本周' → 本周一 ~ 本周日"""
        from app.tools.retrieval.time_resolver import TimeResolverTool

        result = _run(TimeResolverTool(), time_expression="本周")
        assert result.success is True
        start = datetime.fromisoformat(result.data["start"])
        end = datetime.fromisoformat(result.data["end"])
        assert start.date() <= date.today() <= end.date()

    def test_this_month(self):
        """'本月' → 本月1日 ~ 本月最后一日"""
        from app.tools.retrieval.time_resolver import TimeResolverTool

        result = _run(TimeResolverTool(), time_expression="本月")
        assert result.success is True
        start = datetime.fromisoformat(result.data["start"])
        end = datetime.fromisoformat(result.data["end"])
        assert start.day == 1
        assert end.day >= 28  # 月最后一天至少28号

    def test_last_month(self):
        """'上个月' → 上月1日 ~ 上月最后一日"""
        from app.tools.retrieval.time_resolver import TimeResolverTool

        result = _run(TimeResolverTool(), time_expression="上个月")
        assert result.success is True
        start = datetime.fromisoformat(result.data["start"])
        end = datetime.fromisoformat(result.data["end"])
        today = date.today()
        assert start.month != today.month or start.year != today.year

    def test_recent_n_days(self):
        """测试要点 3: '最近3天' → 3天前 ~ 今天"""
        from app.tools.retrieval.time_resolver import TimeResolverTool

        result = _run(TimeResolverTool(), time_expression="最近3天")
        assert result.success is True
        start = datetime.fromisoformat(result.data["start"])
        end = datetime.fromisoformat(result.data["end"])
        delta = (end.date() - start.date()).days
        assert delta == 3, f"期望 3 天范围，实际 {delta}"

    def test_recent_n_weeks(self):
        """'最近2周' → 14天前 ~ 今天"""
        from app.tools.retrieval.time_resolver import TimeResolverTool

        result = _run(TimeResolverTool(), time_expression="最近2周")
        assert result.success is True
        start = datetime.fromisoformat(result.data["start"])
        end = datetime.fromisoformat(result.data["end"])
        delta = (end.date() - start.date()).days
        assert 13 <= delta <= 14

    def test_recent_n_months(self):
        """'最近1月' → 30天前 ~ 今天"""
        from app.tools.retrieval.time_resolver import TimeResolverTool

        result = _run(TimeResolverTool(), time_expression="最近1月")
        assert result.success is True
        start = datetime.fromisoformat(result.data["start"])
        end = datetime.fromisoformat(result.data["end"])
        delta = (end.date() - start.date()).days
        assert 29 <= delta <= 30

    def test_recent_with_spaces(self):
        """'最近 7 天' (带空格) → 正确解析"""
        from app.tools.retrieval.time_resolver import TimeResolverTool

        result = _run(TimeResolverTool(), time_expression="最近 7 天")
        assert result.success is True

    def test_rule_not_matched_no_llm(self):
        """测试要点 5: '香蕉' 规则不匹配 + 无 LLM → success=False"""
        from app.tools.retrieval.time_resolver import TimeResolverTool

        result = _run(TimeResolverTool(), time_expression="香蕉")
        assert result.success is False
        assert "规则无法解析" in result.error


class TestTimeResolverLLMFallback:
    """LLM 兜底测试"""

    def test_llm_fallback_called(self):
        """
        测试要点 4: '去年三月' 规则不匹配 → LLM 兜底 → confidence < 1.0
        """
        from unittest.mock import AsyncMock

        from app.tools.retrieval.time_resolver import TimeResolverTool

        mock_llm = AsyncMock()
        mock_llm.parse_json.return_value = {
            "start": "2025-03-01T00:00:00",
            "end": "2025-03-31T23:59:59",
            "confidence": 0.85,
        }

        tool = TimeResolverTool()
        result = _run(
            tool,
            time_expression="去年三月",
            llm_client=mock_llm,
        )

        assert result.success is True
        assert result.data["resolution_method"] == "llm"
        assert result.data["confidence"] < 1.0
        assert "2025-03" in result.data["start"]

    def test_llm_returns_none(self):
        """LLM 返回 None (解析失败) → success=False"""
        from unittest.mock import AsyncMock

        from app.tools.retrieval.time_resolver import TimeResolverTool

        mock_llm = AsyncMock()
        mock_llm.parse_json.return_value = None

        tool = TimeResolverTool()
        result = _run(
            tool,
            time_expression="火星历法时间",
            llm_client=mock_llm,
        )

        assert result.success is False
        assert "LLM" in result.error


class TestTimeResolverRegistration:
    """工具注册 + Schema"""

    def test_register(self):
        from app.tools.registry import ToolRegistry
        from app.tools.retrieval.time_resolver import TimeResolverTool

        registry = ToolRegistry()
        registry.register(TimeResolverTool)
        tool = registry.get_tool("time_resolver")
        assert tool is not None

    def test_schema(self):
        from app.tools.retrieval.time_resolver import TimeResolverTool

        schema = TimeResolverTool().to_json_schema()
        assert schema["name"] == "time_resolver"
        assert "time_expression" in schema["parameters"]["required"]
