"""
SlowRouter 单元测试

测试要点（对齐 slow_router.py v2 规则优先设计）：
  1. react:       普通查询 → react（规则默认）
  2. plan:        含对比/制定计划等词 → plan（规则）
  3. multi_agent: 含月报/年报等词 → multi_agent（规则）
  4. 空输入 → react（fallback，不调 LLM）
  5. SlowRouterResult 属性：is_react / is_plan / is_multi_agent
  6. to_dict() 结构正确
  7. memory_context 不影响规则结果（不报错）
"""
from __future__ import annotations

import asyncio

from app.orchestration.slow_router import SlowRouter, SlowRouterResult


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ──────────────────────────────────────────────────────────────────
# 测试：规则路径
# ──────────────────────────────────────────────────────────────────

def test_react_path():
    """普通查询 → react（规则默认）"""
    router = SlowRouter()
    result = run(router.route("我昨天记了啥"))
    assert result.path == "react"
    assert result.decided_by == "rule"
    assert result.is_react is True
    assert result.is_plan is False
    assert result.is_multi_agent is False


def test_plan_path():
    """含对比词 → plan（规则）"""
    router = SlowRouter()
    result = run(router.route("对比我记的两个健身方案"))
    assert result.path == "plan"
    assert result.decided_by == "rule"
    assert result.is_plan is True


def test_multi_agent_path():
    """含月报词 → multi_agent（规则）"""
    router = SlowRouter()
    result = run(router.route("生成我这个月的学习月报"))
    assert result.path == "multi_agent"
    assert result.decided_by == "rule"
    assert result.is_multi_agent is True


def test_plan_keyword_zhi_ding():
    """'制定计划' → plan"""
    router = SlowRouter()
    result = run(router.route("帮我制定计划"))
    assert result.path == "plan"
    assert result.decided_by == "rule"


def test_multi_agent_keyword_nian_bao():
    """'年报' → multi_agent"""
    router = SlowRouter()
    result = run(router.route("生成年报"))
    assert result.path == "multi_agent"
    assert result.decided_by == "rule"


def test_react_default_long_sentence():
    """无关键词的长句 → react（规则默认）"""
    router = SlowRouter()
    result = run(router.route("帮我找所有Python相关笔记并整理一下"))
    assert result.path == "react"
    assert result.decided_by == "rule"


# ──────────────────────────────────────────────────────────────────
# 测试：fallback（空输入）
# ──────────────────────────────────────────────────────────────────

def test_fallback_empty_input():
    """空输入 → react fallback（不调 LLM）"""
    called = []
    def spy(**kwargs):
        called.append(True)
        return {"path": "plan"}

    router = SlowRouter(llm_parse_json=spy)
    result = run(router.route(""))
    assert result.path == "react"
    assert result.decided_by == "fallback"
    assert len(called) == 0  # 空输入不应调 LLM


# ──────────────────────────────────────────────────────────────────
# 测试：数据结构
# ──────────────────────────────────────────────────────────────────

def test_to_dict():
    """to_dict() 包含 path / reason / decided_by"""
    result = SlowRouterResult(path="plan", reason="固定步骤", decided_by="rule")
    d = result.to_dict()
    assert d["path"] == "plan"
    assert d["reason"] == "固定步骤"
    assert d["decided_by"] == "rule"


def test_default_result():
    """SlowRouterResult 默认值"""
    result = SlowRouterResult()
    assert result.path == "react"
    assert result.decided_by == "llm"
    assert result.is_react is True


# ──────────────────────────────────────────────────────────────────
# 测试：memory_context 传入（规则层不使用，不报错即可）
# ──────────────────────────────────────────────────────────────────

def test_with_memory_context():
    """memory_context 传入不报错，规则层正常判定"""
    router = SlowRouter()
    ctx = {
        "recent_turns": [
            {"role": "user", "content": "昨天记了什么"},
            {"role": "assistant", "content": "你昨天记了关于Python的笔记"},
        ],
        "active_goals": ["三个月内掌握后端开发"],
    }
    result = run(router.route("继续帮我查相关记录", memory_context=ctx))
    assert result.path == "react"
    assert result.decided_by == "rule"


def test_with_empty_memory_context():
    """memory_context 为空时正常工作"""
    router = SlowRouter()
    result = run(router.route("我昨天记了啥", memory_context={}))
    assert result.path == "react"
    assert result.decided_by == "rule"


def test_memory_context_none():
    """memory_context=None 时正常工作（默认值）"""
    router = SlowRouter()
    result = run(router.route("我昨天记了啥", memory_context=None))
    assert result.path == "react"
    assert result.decided_by == "rule"
