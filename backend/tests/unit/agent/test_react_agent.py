"""
ReAct Agent 单元测试

测试要点（对齐 react_agent.py 文档）：
  1. 简单查询(1轮): 工具返回结果 → LLM 生成答案 → status=success
  2. 多轮探索: 工具调两次后 LLM 给出答案
  3. MAX_ROUNDS 保护: 工具永远触发 tool_call → 10轮后 status=partial
  4. 无记录: 工具返回空 → status=success（LLM 诚实回答）
  5. 来源引用: sources 包含实际 memory_id
  6. 工具调用失败: graceful 处理，继续循环
  7. 无 tool_registry → status=no_tool_registry
  8. 空问题 → status=success，answer 为引导语
  9. LLM 不可用 → 降级回答
  10. history 历史对话传入正常
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agent.react_agent import ReActAgent, MAX_ROUNDS
from app.tools.base import ToolResult


# ──────────────────────────────────────────────────────────────────
# 工厂函数
# ──────────────────────────────────────────────────────────────────

def _make_registry(tool_name: str = "hybrid_search", tool_result: ToolResult = None):
    """返回带一个 mock 工具的 registry。"""
    if tool_result is None:
        tool_result = ToolResult(success=True, data=[
            {"memory_id": "m1", "title": "Python闭包笔记", "content": "学习了闭包"},
        ])

    mock_tool = MagicMock()
    mock_tool.name = tool_name
    mock_tool.execute = AsyncMock(return_value=tool_result)
    mock_tool.to_json_schema = MagicMock(return_value={
        "name": tool_name,
        "description": "搜索记忆",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    })

    registry = MagicMock()
    registry.list_tool_schemas.return_value = [mock_tool.to_json_schema()]
    registry.get_tool.return_value = mock_tool

    return registry, mock_tool


def _make_llm_sequence(*responses):
    """依次返回给定的响应列表。"""
    call_count = [0]
    def fn(**kwargs):
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(responses):
            return responses[idx]
        return {"type": "text", "content": "默认回答"}
    return fn


def _text_response(content: str = "找到了相关记录，你昨天记了Python笔记。"):
    return {"type": "text", "content": content}


def _tool_call_response(name: str = "hybrid_search", args: dict = None):
    return {"type": "tool_call", "name": name, "arguments": args or {"query": "Python"}}


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


DB = MagicMock()
USER_ID = uuid4()


# ──────────────────────────────────────────────────────────────────
# 测试：正常路径
# ──────────────────────────────────────────────────────────────────

def test_single_round_success():
    """工具调用 1 次后 LLM 给答案 → status=success"""
    registry, tool = _make_registry()
    llm = _make_llm_sequence(
        _tool_call_response(),
        _text_response("找到了你昨天记的Python笔记。"),
    )
    agent = ReActAgent(tool_registry=registry, llm_function_call=llm)
    result = run(agent.run(DB, USER_ID, {"question": "我昨天记了啥"}))

    assert result["status"] == "success"
    assert result["data"]["answer"] == "找到了你昨天记的Python笔记。"
    assert result["data"]["tool_calls_made"] == 1
    assert result["data"]["rounds"] == 2
    assert result["_context"]["tool_calls_count"] == 1


def test_multi_round():
    """工具调用 2 次后给答案 → status=success, rounds=3"""
    registry, tool = _make_registry()
    llm = _make_llm_sequence(
        _tool_call_response("hybrid_search", {"query": "Python"}),
        _tool_call_response("hybrid_search", {"query": "闭包"}),
        _text_response("你记了闭包相关的内容。"),
    )
    agent = ReActAgent(tool_registry=registry, llm_function_call=llm)
    result = run(agent.run(DB, USER_ID, {"question": "帮我找所有Python笔记"}))

    assert result["status"] == "success"
    assert result["data"]["tool_calls_made"] == 2
    assert result["data"]["rounds"] == 3


def test_sources_extracted():
    """来源引用：sources 包含 memory_id"""
    tool_result = ToolResult(success=True, data=[
        {"memory_id": "abc123", "title": "学习笔记"},
        {"memory_id": "def456", "title": "工作记录"},
    ])
    registry, _ = _make_registry(tool_result=tool_result)
    llm = _make_llm_sequence(
        _tool_call_response(),
        _text_response("找到了两条记录。"),
    )
    agent = ReActAgent(tool_registry=registry, llm_function_call=llm)
    result = run(agent.run(DB, USER_ID, {"question": "有什么记录"}))

    sources = result["data"]["sources"]
    assert len(sources) == 2
    assert sources[0]["memory_id"] == "abc123"
    assert sources[1]["memory_id"] == "def456"


def test_no_records_honest_answer():
    """工具返回空 → LLM 被告知无结果，status=success"""
    tool_result = ToolResult(success=True, data=[])
    registry, _ = _make_registry(tool_result=tool_result)
    llm = _make_llm_sequence(
        _tool_call_response(),
        _text_response("没有找到相关记录。"),
    )
    agent = ReActAgent(tool_registry=registry, llm_function_call=llm)
    result = run(agent.run(DB, USER_ID, {"question": "找Python记录"}))

    assert result["status"] == "success"
    assert "没有" in result["data"]["answer"]
    assert result["data"]["sources"] == []


# ──────────────────────────────────────────────────────────────────
# 测试：MAX_ROUNDS 保护
# ──────────────────────────────────────────────────────────────────

def test_max_rounds_protection():
    """LLM 永远返回 tool_call → MAX_ROUNDS 后 status=partial"""
    registry, _ = _make_registry()
    # 永远返回 tool_call，不给出 text
    llm = _make_llm_sequence(*[_tool_call_response() for _ in range(MAX_ROUNDS + 5)])
    agent = ReActAgent(tool_registry=registry, llm_function_call=llm)
    result = run(agent.run(DB, USER_ID, {"question": "一直搜索"}))

    assert result["status"] == "partial"
    assert result["data"]["rounds"] == MAX_ROUNDS
    assert result["data"]["tool_calls_made"] == MAX_ROUNDS


# ──────────────────────────────────────────────────────────────────
# 测试：工具调用失败
# ──────────────────────────────────────────────────────────────────

def test_tool_call_failure_graceful():
    """工具抛出异常 → graceful 处理，继续循环，最终给答案"""
    registry = MagicMock()
    registry.list_tool_schemas.return_value = [{"name": "bad_tool", "description": "会出错的工具", "parameters": {}}]
    registry.get_tool.return_value = None  # get_tool 返回 None → _call_tool 内部会失败

    llm = _make_llm_sequence(
        {"type": "tool_call", "name": "bad_tool", "arguments": {}},
        _text_response("虽然出错了，还是给你答案。"),
    )
    agent = ReActAgent(tool_registry=registry, llm_function_call=llm)
    result = run(agent.run(DB, USER_ID, {"question": "测试工具出错"}))

    # 不应该崩溃，给出最终答案
    assert result["status"] == "success"
    assert "答案" in result["data"]["answer"]


# ──────────────────────────────────────────────────────────────────
# 测试：边界条件
# ──────────────────────────────────────────────────────────────────

def test_no_tool_registry():
    """无 tool_registry → status=no_tool_registry"""
    agent = ReActAgent(tool_registry=None, llm_function_call=_make_llm_sequence())
    result = run(agent.run(DB, USER_ID, {"question": "我的记录"}))
    assert result["status"] == "no_tool_registry"


def test_empty_question():
    """空问题 → status=success，answer 为引导语"""
    registry, _ = _make_registry()
    agent = ReActAgent(tool_registry=registry, llm_function_call=_make_llm_sequence())
    result = run(agent.run(DB, USER_ID, {"question": ""}))
    assert result["status"] == "success"
    assert result["data"]["tool_calls_made"] == 0


def test_llm_unavailable():
    """LLM 返回 None → 降级回答"""
    registry, _ = _make_registry()
    agent = ReActAgent(tool_registry=registry, llm_function_call=lambda **kw: None)
    result = run(agent.run(DB, USER_ID, {"question": "我的记录"}))
    assert result["status"] == "success"
    assert result["data"]["tool_calls_made"] == 0


def test_with_history():
    """带历史对话 → 不报错，正常处理"""
    registry, _ = _make_registry()
    llm = _make_llm_sequence(
        _tool_call_response(),
        _text_response("根据历史和记录，给你答案。"),
    )
    agent = ReActAgent(tool_registry=registry, llm_function_call=llm)
    history = [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好，有什么可以帮你的？"},
    ]
    result = run(agent.run(DB, USER_ID, {"question": "继续上次的查询", "history": history}))
    assert result["status"] == "success"


def test_context_metadata():
    """_context 包含 trajectory_length 和 tool_calls_count"""
    registry, _ = _make_registry()
    llm = _make_llm_sequence(
        _tool_call_response(),
        _text_response("找到了。"),
    )
    agent = ReActAgent(tool_registry=registry, llm_function_call=llm)
    result = run(agent.run(DB, USER_ID, {"question": "查找"}))

    assert "_context" in result
    assert "trajectory_length" in result["_context"]
    assert result["_context"]["tool_calls_count"] >= 1


def test_arguments_as_json_string():
    """arguments 是 JSON 字符串时也能正确解析"""
    registry, _ = _make_registry()
    llm = _make_llm_sequence(
        {"type": "tool_call", "name": "hybrid_search", "arguments": '{"query": "Python"}'},
        _text_response("找到了。"),
    )
    agent = ReActAgent(tool_registry=registry, llm_function_call=llm)
    result = run(agent.run(DB, USER_ID, {"question": "找Python"}))
    assert result["status"] == "success"
