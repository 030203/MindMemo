"""
QAWorkflow 编排集成测试 (Phase 3-A 更新)

测试要点:
  1. fast: "你好" → route.complexity=fast，走 QAAgent
  2. slow: "分析学习记录" → slow → SlowRouter → ReActAgent
  3. slow: plan/multi_agent → 当前降级为 react，正常运行
  4. LLM 不可用 → status 透传，不崩溃
  5. slow 结果包含 sources / slow_route 字段
  6. 输出结构正确
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.orchestration.router import Router
from app.orchestration.slow_router import SlowRouter, SlowRouterResult
from app.agent.qa_agent import QAAgent, QAResult
from app.agent.react_agent import ReActAgent
from app.orchestration.qa_workflow import QAWorkflow


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ──────────────────────────────────────────────────────────────────
# 工厂函数
# ──────────────────────────────────────────────────────────────────

def _make_fast_workflow(answer="好的"):
    """Fast 路径：纯 QAAgent，不走 slow。"""
    router = Router(llm_parse_json=None)
    agent = QAAgent(llm_chat=lambda system_prompt, user_prompt: answer)
    return QAWorkflow(router=router, qa_agent=agent)


def _make_slow_workflow(react_answer="找到了相关记录"):
    """Slow 路径：SlowRouter 返回 react，ReActAgent 注入。"""
    router = Router(llm_parse_json=None)
    qa_agent = QAAgent(llm_chat=lambda **kw: "fast answer")

    slow_router = SlowRouter(llm_parse_json=lambda **kw: {"path": "react", "reason": "探索式"})

    # mock ReActAgent
    react_agent = MagicMock(spec=ReActAgent)
    react_agent.run = AsyncMock(return_value={
        "status": "success",
        "data": {
            "answer": react_answer,
            "sources": [{"memory_id": "m1", "title": "笔记"}],
            "tool_calls_made": 1,
            "rounds": 2,
        },
        "_context": {"trajectory_length": 2, "tool_calls_count": 1, "duration_ms": 100},
    })

    return QAWorkflow(
        router=router,
        qa_agent=qa_agent,
        slow_router=slow_router,
        react_agent=react_agent,
    )


# ──────────────────────────────────────────────────────────────────
# Fast 路径测试
# ──────────────────────────────────────────────────────────────────

class TestFastPath:
    def test_fast_route(self):
        wf = _make_fast_workflow(answer="你好呀")
        out = run(wf.run("你好"))
        assert out["route"]["complexity"] == "fast"
        assert out["status"] == "success"
        assert out["answer"] == "你好呀"

    def test_llm_unavailable_propagates(self):
        router = Router(llm_parse_json=None)
        agent = QAAgent(llm_chat=lambda **kw: None)
        wf = QAWorkflow(router=router, qa_agent=agent)
        out = run(wf.run("你好"))
        assert out["status"] == "unavailable"
        assert "不可用" in out["answer"]

    def test_fast_output_shape(self):
        wf = _make_fast_workflow()
        out = run(wf.run("你好"))
        assert "answer" in out
        assert "status" in out
        assert "route" in out
        assert set(out["route"].keys()) == {"complexity", "reason", "suggested_tools", "decided_by"}

    def test_empty_question(self):
        wf = _make_fast_workflow()
        out = run(wf.run(""))
        assert out["route"]["complexity"] == "fast"
        assert out["status"] == "success"


# ──────────────────────────────────────────────────────────────────
# Slow 路径测试
# ──────────────────────────────────────────────────────────────────

class TestSlowPath:
    def test_slow_route_calls_react(self):
        wf = _make_slow_workflow(react_answer="找到了你的学习记录。")
        out = run(wf.run("分析最近一个月的学习记录"))
        assert out["route"]["complexity"] == "slow"
        assert out["status"] == "success"
        assert out["answer"] == "找到了你的学习记录。"

    def test_slow_result_has_sources(self):
        wf = _make_slow_workflow()
        out = run(wf.run("我昨天记了啥"))
        assert "sources" in out
        assert len(out["sources"]) > 0
        assert out["sources"][0]["memory_id"] == "m1"

    def test_slow_result_has_slow_route(self):
        wf = _make_slow_workflow()
        out = run(wf.run("分析我的学习效率"))  # 命中 slow 意图词
        assert "slow_route" in out
        assert out["slow_route"]["path"] == "react"
        assert out["slow_route"]["decided_by"] == "rule"

    def test_slow_plan_path_degrades_to_react(self):
        """plan 路径当前降级为 react，不报错"""
        router = Router(llm_parse_json=None)
        slow_router = SlowRouter(
            llm_parse_json=lambda **kw: {"path": "plan", "reason": "固定步骤"}
        )
        react_agent = MagicMock(spec=ReActAgent)
        react_agent.run = AsyncMock(return_value={
            "status": "success",
            "data": {"answer": "对比结果", "sources": [], "tool_calls_made": 2, "rounds": 3},
            "_context": {},
        })
        wf = QAWorkflow(
            router=router,
            qa_agent=QAAgent(llm_chat=lambda **kw: "x"),
            slow_router=slow_router,
            react_agent=react_agent,
        )
        out = run(wf.run("对比我记的两个健身方案"))
        assert out["status"] == "success"
        assert out["slow_route"]["path"] == "plan"
        assert out["answer"] == "对比结果"

    def test_slow_multi_agent_path_degrades_to_react(self):
        """multi_agent 路径当前降级为 react，不报错"""
        router = Router(llm_parse_json=None)
        slow_router = SlowRouter(
            llm_parse_json=lambda **kw: {"path": "multi_agent", "reason": "并行扇出"}
        )
        react_agent = MagicMock(spec=ReActAgent)
        react_agent.run = AsyncMock(return_value={
            "status": "success",
            "data": {"answer": "月报内容", "sources": [], "tool_calls_made": 5, "rounds": 5},
            "_context": {},
        })
        wf = QAWorkflow(
            router=router,
            qa_agent=QAAgent(llm_chat=lambda **kw: "x"),
            slow_router=slow_router,
            react_agent=react_agent,
        )
        out = run(wf.run("生成我这个月的学习月报"))
        assert out["status"] == "success"
        assert out["slow_route"]["path"] == "multi_agent"
