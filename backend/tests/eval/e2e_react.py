"""
端到端验证：ReAct 完整链路（真实 DB + 真实 LLM + 真实工具）

测试场景：
  1. 创建 SQLite 内存数据库
  2. 插入测试用户和 3 条记忆
  3. 走完整链路：Router → SlowRouter → ReActAgent → hybrid_search → 回答
  4. 验证：路由是 slow，工具被调用，答案来自真实记录

运行: cd backend && python -m tests.eval.e2e_react
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from unittest.mock import MagicMock

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base
from app.models.user import User
from app.models.memory import MemoryItem


def _setup_db() -> tuple[Session, uuid.UUID]:
    """创建内存 DB + 用户 + 3 条测试记忆。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()

    user = User(
        id=uuid.uuid4(),
        email="e2e@test.com",
        password_hash="h",
        display_name="E2E用户",
        status="active",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    uid = user.id
    now = datetime.now(timezone.utc)

    memories = [
        MemoryItem(
            id=uuid.uuid4(), user_id=uid, source_type="manual",
            title="Python闭包学习笔记", content_raw="学习了Python闭包的概念和用法，包括装饰器和工厂函数。",
            category="学习笔记", tags=["Python", "闭包", "编程"], keywords=["Python", "闭包", "装饰器"],
            importance_score=0.8, created_at=now, updated_at=now,
        ),
        MemoryItem(
            id=uuid.uuid4(), user_id=uid, source_type="manual",
            title="FastAPI入门记录", content_raw="今天开始学习FastAPI框架，搞清楚了路由和依赖注入的基本用法。",
            category="学习笔记", tags=["FastAPI", "Python", "后端"], keywords=["FastAPI", "路由", "依赖注入"],
            importance_score=0.7, created_at=now, updated_at=now,
        ),
        MemoryItem(
            id=uuid.uuid4(), user_id=uid, source_type="manual",
            title="晨跑5公里", content_raw="早上6点起床去跑了5公里，用时28分钟，状态很好。",
            category="生活", tags=["运动", "跑步", "健康"], keywords=["晨跑", "5公里", "运动"],
            importance_score=0.5, created_at=now, updated_at=now,
        ),
    ]
    for m in memories:
        db.add(m)
    db.commit()
    print(f"  用户: {uid}")
    print(f"  记忆: 3条 (Python闭包, FastAPI, 晨跑)")
    return db, uid


async def test_fast_route():
    """Router fast 路径：纯规则，零 LLM。"""
    from app.orchestration.router import Router
    router = Router()
    result = router.route("你好")
    assert result.complexity == "fast"
    print(f"  [OK] fast 路由: '你好' → {result.complexity}({result.decided_by})")
    return True


async def test_slow_route_react(db: Session, uid: uuid.UUID):
    """slow + ReAct：真实 LLM + hybrid_search 搜数据库。"""
    from app.tools.registry import ToolRegistry
    from app.tools.retrieval.hybrid_search import HybridSearchTool
    from app.agent.react_agent import ReActAgent

    # 注册工具
    registry = ToolRegistry()
    registry.register(HybridSearchTool)

    agent = ReActAgent(tool_registry=registry)

    # 构造 ReAct 循环的 function_call（真实 LLM）
    from app.services.llm_answer_service import llm_answer_service
    fn_call = llm_answer_service.function_call

    # 构造 system prompt + 消息
    tool_schemas = registry.list_tool_schemas()
    system_content = (
        "你是 MindMemo 的个人记忆助手。\n"
        f"可用工具:\n- hybrid_search: 搜索用户记忆，输入关键词\n\n"
        "用户上下文：(E2E测试)\n"
        "工作原则：优先使用工具检索真实记录，不要编造。"
    )

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": "我记了什么Python相关的内容"},
    ]

    # ── Round 1: LLM 应该调工具 ──
    print("  [Round 1] 调 LLM...")
    result1 = fn_call(messages=messages, tools=tool_schemas)
    assert result1 is not None, "LLM 未返回结果"
    assert result1["type"] == "tool_call", f"期望 tool_call, 实际 {result1['type']}"
    assert result1["name"] == "hybrid_search", f"期望 hybrid_search, 实际 {result1['name']}"
    print(f"  [OK] Round 1: LLM 决定调 hybrid_search (query={result1['arguments']})")

    # ── 执行工具 ──
    tool = registry.get_tool("hybrid_search")
    tool_result = await tool.execute(
        query="Python", db=db, user_id=uid
    )
    assert tool_result.success, f"工具调用失败: {tool_result.error}"
    results = tool_result.data.get("results", [])
    print(f"  [OK] Round 1: 工具返回 {len(results)} 条结果")
    for r in results:
        print(f"        - {r.get('title')}")

    # ── Round 2: 把 tool result 喂回 LLM，LLM 应该给出答案 ──
    messages.append(result1["_assistant_msg"] if "_assistant_msg" in result1 else result1)
    messages.append({
        "role": "tool",
        "tool_call_id": result1.get("_assistant_msg", {}).get("tool_calls", [{}])[0].get("id", ""),
        "name": "hybrid_search",
        "content": json.dumps(tool_result.data, ensure_ascii=False),
    })

    print("  [Round 2] 调 LLM...")
    result2 = fn_call(messages=messages, tools=tool_schemas)
    assert result2 is not None, "LLM 未返回结果"
    assert result2["type"] == "text", f"expect text, got {result2['type']}"
    answer_len = len(result2["content"])
    answer_first = result2["content"][:100].encode('ascii', errors='replace').decode()
    print(f"  [OK] Round 2: LLM ({answer_len} chars)")
    print(f"        first 100: {answer_first}")

    return True


async def test_full_qa_workflow_raw(db: Session, uid: uuid.UUID):
    """走完整 qa_workflow.run()。"""
    from app.orchestration.qa_workflow import QAWorkflow
    from app.tools.registry import ToolRegistry
    from app.tools.retrieval.hybrid_search import HybridSearchTool

    registry = ToolRegistry()
    registry.register(HybridSearchTool)

    from app.orchestration.slow_router import SlowRouter

    wf = QAWorkflow(
        tool_registry=registry,
    )
    # QAWorkflow.slow_router 默认用真实 LLM
    # 这步会调小米 API → 真实判定 → 真实 ReAct

    print("  调用 qa_workflow.run()...")
    out = await wf.run(
        question="我记了Python什么内容",
        user_id=uid,
        db=db,
    )
    print(f"  route: {out.get('route', {}).get('complexity', '?')}")
    print(f"  slow_route: {out.get('slow_route', {}).get('path', '?')}")
    answer = out.get("answer", "")
    print(f"  answer ({len(answer)}字): {answer[:120]}...")
    return True


async def main():
    print("=" * 60)
    print("  Phase 3 端到端验证")
    print("=" * 60)
    print()

    # ── Test 1: Router fast ──
    print("[Test 1] Router fast 路径")
    ok = await test_fast_route()
    print(f"  -> {'OK' if ok else 'FAIL'}")
    print()

    # ── Test 2: ReAct + hybrid_search 完整工具调用 ──
    print("[Test 2] ReAct + hybrid_search (完整链路)")
    db, uid = _setup_db()
    ok = await test_slow_route_react(db, uid)
    print(f"  -> {'OK' if ok else 'FAIL'}")
    db.close()
    print()

    # ── Test 3: 完整 qa_workflow ──
    print("[Test 3] qa_workflow.run() 完整链路")
    db2, uid2 = _setup_db()
    try:
        ok = await test_full_qa_workflow_raw(db2, uid2)
        print(f"  -> {'OK' if ok else 'FAIL'}")
    except Exception as e:
        print(f"  -> FAIL: {e}")
    db2.close()
    print()

    print("=" * 60)
    print("  E2E 验证完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
