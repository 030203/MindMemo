"""
TimeResolverTool - 时间表达式解析器

职责：把自然语言时间表达转为精确 ISO 8601 日期范围
      "上周" → {start: "2026-06-16T00:00:00", end: "2026-06-22T23:59:59"}

设计原则：
- 规则优先：常见表达式用正则直接解析，零延迟、零成本
- LLM 兜底：规则匹配失败时才调 LLM，避免不必要的 API 调用

============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  time_expression: str  # "上周", "本月", "最近3天", "去年三月"

[步骤2] 规则优先解析 (不调 LLM)
  规则表 (按优先级):
    "今天"     → 今天 00:00:00 ~ 23:59:59
    "昨天"     → 昨天 00:00:00 ~ 23:59:59
    "明天"     → 明天 00:00:00 ~ 23:59:59
    "本周"     → 本周一 00:00 ~ 本周日 23:59
    "上周"     → 上周一 00:00 ~ 上周日 23:59
    "下周"     → 下周一 00:00 ~ 下周日 23:59
    "本月"     → 本月1日 00:00 ~ 本月最后一日 23:59
    "上个月"   → 上月1日 00:00 ~ 上月最后一日 23:59
    "最近N天"  → N天前 00:00 ~ 今天 23:59
    "最近N周"  → N*7天前 00:00 ~ 今天 23:59
    "最近N月"  → N*30天前 00:00 ~ 今天 23:59

[步骤3] 规则未命中 → LLM 兜底
  调 LLMClient.parse_json(
    prompt=time_expression,
    schema={type: object, properties: {start, end, confidence}}
  )
  标记 resolution_method="llm", confidence < 1.0

[步骤4] 返回 ToolResult
  ToolResult(
    success=True,
    data={
      "start": "2026-06-16T00:00:00+08:00",
      "end": "2026-06-22T23:59:59+08:00",
      "confidence": 0.95,
      "resolution_method": "rule" | "llm"
    }
  )

============================================================
测试要点:
  1. "今天" → 正确日期范围
  2. "上周" → 周一~周日
  3. "最近3天" → 3天前~今天
  4. "去年三月" → LLM兜底, confidence < 1.0
  5. 非法输入: "香蕉" → success=False
============================================================
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, time, timedelta, timezone

from app.tools.base import BaseTool, ToolResult, ToolParameter, ToolParameterType

# ----------------------------------------------------------------
# 规则解析器 —— 零 LLM 成本的时间表达式转换
# ----------------------------------------------------------------

# 预设规则: (正则, 解析函数)
# 按匹配优先级排列，越具体越靠前
_RULES: list[tuple[re.Pattern, callable]] = []


def _now() -> date:
    """当前日期（可 mock 用于测试）"""
    return date.today()


def _start_of_day(d: date) -> datetime:
    return datetime.combine(d, time.min)

def _end_of_day(d: date) -> datetime:
    return datetime.combine(d, time.max)


def _parse_recent_n(pattern: re.Pattern, text: str) -> dict | None:
    """解析 '最近N天' / '最近N周' / '最近N月'"""
    m = pattern.match(text.strip())
    if not m:
        return None
    n = int(m.group(1))
    today = _now()
    unit = m.group(2)
    if unit in ("天", "日"):
        start_date = today - timedelta(days=n)
    elif unit == "周":
        start_date = today - timedelta(days=n * 7)
    elif unit == "月":
        # 粗略: n*30天前
        start_date = today - timedelta(days=n * 30)
    else:
        return None
    return {
        "start": _start_of_day(start_date).isoformat(),
        "end": _end_of_day(today).isoformat(),
        "confidence": 1.0,
        "resolution_method": "rule",
    }


def _parse_relative_day(text: str) -> dict | None:
    """解析 '今天' / '昨天' / '明天'"""
    today = _now()
    mapping = {
        "今天": today,
        "昨天": today - timedelta(days=1),
        "明天": today + timedelta(days=1),
    }
    for word, d in mapping.items():
        if word in text:
            return {
                "start": _start_of_day(d).isoformat(),
                "end": _end_of_day(d).isoformat(),
                "confidence": 1.0,
                "resolution_method": "rule",
            }
    return None


def _parse_relative_week(text: str) -> dict | None:
    """解析 '本周' / '上周' / '下周'"""
    today = _now()
    weekday = today.weekday()  # 0=Mon, 6=Sun
    mapping = {
        "本周": 0,
        "上周": -1,
        "下周": 1,
    }
    for word, offset in mapping.items():
        if word in text:
            monday = today - timedelta(days=weekday) + timedelta(weeks=offset)
            sunday = monday + timedelta(days=6)
            return {
                "start": _start_of_day(monday).isoformat(),
                "end": _end_of_day(sunday).isoformat(),
                "confidence": 1.0,
                "resolution_method": "rule",
            }
    return None


def _parse_relative_month(text: str) -> dict | None:
    """解析 '本月' / '上个月' / '下个月'"""
    today = _now()
    if "上个月" in text or "上月" in text:
        year, month = today.year, today.month - 1
        if month == 0:
            year -= 1
            month = 12
    elif "下个月" in text or "下月" in text:
        year, month = today.year, today.month + 1
        if month == 13:
            year += 1
            month = 1
    elif "本月" in text or "这个月" in text:
        year, month = today.year, today.month
    else:
        return None

    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    return {
        "start": _start_of_day(first_day).isoformat(),
        "end": _end_of_day(last_day).isoformat(),
        "confidence": 1.0,
        "resolution_method": "rule",
    }


def _resolve_by_rules(text: str) -> dict | None:
    """依次尝试所有规则，返回第一个匹配结果，无匹配返回 None"""
    # 1. 最近N天/周/月 (正则优先，防止被部分匹配)
    recent_re = re.compile(r"最近\s*(\d+)\s*(天|周|月|日)")
    result = _parse_recent_n(recent_re, text)
    if result:
        return result

    # 2. 今天/昨天/明天
    result = _parse_relative_day(text)
    if result:
        return result

    # 3. 本周/上周/下周
    result = _parse_relative_week(text)
    if result:
        return result

    # 4. 本月/上个月/下个月
    result = _parse_relative_month(text)
    if result:
        return result

    return None


# ----------------------------------------------------------------
# LLM 兜底 Schema
# ----------------------------------------------------------------

_TIME_SCHEMA = {
    "type": "object",
    "properties": {
        "start": {
            "type": "string",
            "description": "开始时间 ISO 8601 格式，如 2026-03-01T00:00:00",
        },
        "end": {
            "type": "string",
            "description": "结束时间 ISO 8601 格式，如 2026-03-31T23:59:59",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "置信度，规则匹配=1.0，LLM匹配=实际信心",
        },
    },
    "required": ["start", "end", "confidence"],
}


# ----------------------------------------------------------------
# Tool 定义
# ----------------------------------------------------------------

class TimeResolverTool(BaseTool):
    """
    时间表达式解析器 — 把自然语言时间转为精确日期范围

    策略：规则优先（零延迟）+ LLM 兜底（处理复杂表达式）
    """

    name: str = "time_resolver"
    description: str = (
        "把自然语言时间表达转为精确日期范围。"
        "输入如'上周''本月''最近3天'，返回 ISO 8601 格式的起止时间。"
        "用于时间检索的前置步骤 —— Agent 先调此工具解析时间，再调 hybrid_search 检索。"
    )
    parameters: list[ToolParameter] = [
        ToolParameter(
            name="time_expression",
            type=ToolParameterType.STRING,
            description="自然语言时间表达式，如'上周'、'本月'、'最近3天'、'2024年3月'",
            required=True,
        ),
    ]

    async def execute(self, **kwargs) -> ToolResult:
        # [步骤1] 接收参数
        time_expression: str = kwargs.get("time_expression", "")
        if not time_expression or not time_expression.strip():
            return ToolResult(success=False, error="time_expression 不能为空")

        try:
            # [步骤2] 规则优先解析
            rule_result = _resolve_by_rules(time_expression.strip())
            if rule_result is not None:
                return ToolResult(success=True, data=rule_result)

            # [步骤3] LLM 兜底
            # Agent 调用时可通过 kwargs 注入 llm_client
            llm_client = kwargs.get("llm_client")
            if llm_client is None:
                # 无 LLM 客户端时返回失败，不假装知道
                return ToolResult(
                    success=False,
                    error=(
                        f"规则无法解析 '{time_expression}'，"
                        "且未提供 llm_client 做 LLM 兜底。"
                        "请提供更明确的时间表达式，或注入 LLMClient。"
                    ),
                )

            parsed = await llm_client.parse_json(
                prompt=time_expression,
                schema=_TIME_SCHEMA,
            )
            if parsed is None:
                return ToolResult(
                    success=False,
                    error=f"LLM 也无法解析 '{time_expression}'，请使用更明确的时间表达式",
                )

            parsed["resolution_method"] = "llm"
            return ToolResult(success=True, data=parsed)

        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
