"""
QAWorkflow - 问答编排 (Fast / Slow 双链路总装)

职责：把 Router、QAAgent、SlowRouter、ReActAgent 串起来，对外提供统一问答入口。
这是 API 层唯一需要调用的对象。

============================================================
内部处理流程 (Phase 3-A):
============================================================

[步骤1] 接收输入
  question: str
  user_id: UUID (可选，用于加载记忆上下文)
  db: Session (可选，工具需要)
  history: list[dict] (可选，最近对话)

[步骤2] 路由分类 → Router.route()
  得到 RouterResult(fast | slow)

[步骤3] 分流

  fast 路径:
    → QAAgent.answer()  (单轮，不碰记录)

  slow 路径:
    → SlowRouter.route() 二级路由 → path: react | plan | multi_agent
    → react:       ReActAgent.run()  (已实现，Thought→Action→Observation)
    → plan:        降级 ReActAgent (Planner 在 Phase 3-B 接入)
    → multi_agent: 降级 ReActAgent (Multi-Agent 在 Phase 3-C 接入)

[步骤4] 汇总返回
  {answer, status, route, slow_route(可选), sources(可选)}

============================================================
测试要点:
  1. "你好" → route.complexity=fast，走 QAAgent
  2. "分析学习记录" → slow → SlowRouter → ReActAgent
  3. SlowRouter 返回 plan/multi_agent → 当前降级为 react，正常运行
  4. LLM 不可用 → status 透传，不崩溃
  5. slow 路径结果包含 sources 字段
============================================================
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional
from uuid import UUID, uuid4
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.orchestration.router import Router, RouterResult
from app.orchestration.slow_router import SlowRouter
from app.orchestration.planner import Planner
from app.agent.qa_agent import QAAgent
from app.agent.react_agent import ReActAgent

logger = logging.getLogger(__name__)

# Fast 路径白名单：仅外部信息查询工具，不碰用户记录
FAST_TOOL_WHITELIST: frozenset[str] = frozenset({"weather", "web_search"})


class QAWorkflow:
    """
    问答编排器 — Fast / Slow 双链路总入口

    用法：
        wf = QAWorkflow()
        out = await wf.run("你好")

    依赖可注入，便于测试：
        wf = QAWorkflow(router=fake_router, qa_agent=fake_agent, react_agent=fake_react)
    """

    def __init__(
        self,
        router: Optional[Router] = None,
        qa_agent: Optional[QAAgent] = None,
        slow_router: Optional[SlowRouter] = None,
        react_agent: Optional[ReActAgent] = None,
        planner: Optional[Planner] = None,
        tool_registry: Optional[Any] = None,
        memory_manager: Optional[Any] = None,
    ):
        self._router = router or Router()
        self._qa_agent = qa_agent or QAAgent()
        self._slow_router = slow_router or SlowRouter()
        self._planner = planner
        self._react_agent = react_agent
        self._tool_registry = tool_registry
        self._memory_manager = memory_manager

    async def run(
        self,
        question: str,
        history: Optional[list[dict]] = None,
        user_id: Optional[UUID] = None,
        db: Optional[Session] = None,
    ) -> dict:
        # [步骤1] 接收输入
        q = (question or "").strip()

        # [步骤2] 路由分类
        route: RouterResult = self._router.route(q)

        # [步骤3] 分流
        if route.is_fast:
            return await self._handle_fast(q, history, route)
        else:
            return await self._handle_slow(q, history, route, user_id, db)

    # ------------------------------------------------------------------
    # Fast 路径
    # ------------------------------------------------------------------
    async def _handle_fast(
        self,
        question: str,
        history: Optional[list[dict]],
        route: RouterResult,
    ) -> dict:
        return await self._handle_fast_with_tools(question, history)

    async def _handle_fast_with_tools(
        self,
        question: str,
        history: Optional[list[dict]],
    ) -> dict:
        """快速通道 + 工具：小循环（最多 3 轮），LLM 决定是否调工具。

        固定携带 weather + web_search 两个外部工具，LLM 按需调用。
        不需要工具时 LLM 直接返回文本。
        """
        from app.services.llm_answer_service import llm_answer_service
        from app.tools.external.weather import WeatherTool
        from app.tools.external.web_search import WebSearchTool

        tools = [WeatherTool().to_json_schema(), WebSearchTool().to_json_schema()]
        if not tools:
            qa_result = self._qa_agent.answer(question, history=history)
            return {"answer": qa_result.answer, "status": qa_result.status}

        messages: list[dict] = [{"role": "system", "content": "你是 MindMemo 的个人记忆助手。你可以使用工具获取实时信息来回答用户问题。请用自然、简洁、温和的中文回答。"}]
        for turn in (history or [])[-5:]:
            if turn.get("role") in ("user", "assistant") and turn.get("content"):
                messages.append({"role": turn["role"], "content": str(turn["content"])})
        messages.append({"role": "user", "content": question})

        for _ in range(3):  # 最多 3 轮
            result = llm_answer_service.function_call(messages=messages, tools=tools)
            if result is None:
                break  # LLM 不可用，跳出降级

            if result["type"] == "text":
                return {"answer": result["content"], "status": "success"}

            # tool_call
            tool_name = result["name"]
            tool_args = result.get("arguments") or {}
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except Exception:
                    tool_args = {}

            tool = self._tool_registry.get_tool(tool_name)
            if tool is None:
                break

            try:
                raw = await tool.execute(**tool_args)
                obs = raw.data if getattr(raw, "success", False) else f"工具返回错误: {getattr(raw, 'error', '未知错误')}"
            except Exception as exc:
                obs = f"工具调用异常: {exc}"

            # 把 tool_call + tool_result 追加到 messages，下一轮 LLM 据此生成答案
            assistant_msg = result.get("_assistant_msg") or {"role": "assistant", "content": None}
            messages.append(assistant_msg)
            messages.append({"role": "tool", "tool_call_id": (assistant_msg.get("tool_calls") or [{}])[0].get("id", ""), "content": json.dumps(obs, ensure_ascii=False, default=str)})

        # 超轮数 / LLM 无响应 → QAAgent 兜底
        qa_result = self._qa_agent.answer(question, history=history)
        return {"answer": qa_result.answer, "status": qa_result.status}

    # ------------------------------------------------------------------
    # Slow 路径
    # ------------------------------------------------------------------
    async def _handle_slow(
        self,
        question: str,
        history: Optional[list[dict]],
        route: RouterResult,
        user_id: Optional[UUID],
        db: Optional[Session],
    ) -> dict:
        # [步骤3-slow-1] SlowRouter 二级路由
        memory_context = self._get_memory_context()
        slow_result = await self._slow_router.route(question, memory_context=memory_context)

        # [步骤3-slow-2] 按二级路由结果分发
        # Phase 3-A: react 已实现，plan 由 Planner 生成建议步骤注入
        # Phase 3-C: Multi-Agent Coordinator 接入后替换 multi_agent 分支
        agent = self._get_react_agent()

        input_data: dict[str, Any] = {
            "question": question,
            "history": history or [],
            "slow_router_result": slow_result.to_dict(),
        }

        # Plan 路径：启动 Planner -> 生成步骤 -> 注入到 input_data["plan"]
        if slow_result.is_plan:
            plan = self._create_plan(question)
            if plan is not None:
                input_data["plan"] = plan.to_dict()
        # Multi-Agent 路径：创建 Coordinator（ReActAgent + create_sub_agent/collect_results）
        elif slow_result.is_multi_agent:
            coordinator = self._build_coordinator()
            coordinator_result = await coordinator.run(db=db or MagicMock(), user_id=user_id or uuid4(), input_data=input_data)
            data = coordinator_result.get("data") or {}
            return {
                "answer": data.get("answer", ""),
                "status": coordinator_result.get("status", "success"),
                "route": route.to_dict(),
                "slow_route": slow_result.to_dict(),
                "sources": data.get("sources", []),
                "tool_calls_made": data.get("tool_calls_made", 0),
            }

        if db is None:
            db = MagicMock()
        if user_id is None:
            user_id = uuid4()

        react_result = await agent.run(
            db=db,
            user_id=user_id,
            input_data=input_data,
        )

        data = react_result.get("data") or {}
        return {
            "answer": data.get("answer", ""),
            "status": react_result.get("status", "success"),
            "route": route.to_dict(),
            "slow_route": slow_result.to_dict(),
            "sources": data.get("sources", []),
            "tool_calls_made": data.get("tool_calls_made", 0),
        }

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def _get_react_agent(self) -> ReActAgent:
        if self._react_agent is not None:
            return self._react_agent
        return ReActAgent(
            memory_manager=self._memory_manager,
            tool_registry=self._tool_registry,
        )

    def _create_plan(self, question: str) -> Any:
        """调用 Planner 生成执行计划。失败返回 None（降级自由 ReAct）。"""
        if self._planner is not None:
            return self._planner.create_plan(question, self._tool_registry)
        # 延迟创建
        from app.orchestration.planner import Planner
        self._planner = Planner()
        return self._planner.create_plan(question, self._tool_registry)

    def _build_coordinator(self) -> ReActAgent:
        """构建 Multi-Agent Coordinator。"""
        from app.tools.agent.mailbox import Mailbox
        from app.tools.agent.create_sub_agent import CreateSubAgentTool
        from app.tools.agent.collect_results import CollectResultsTool
        from app.tools.registry import ToolRegistry

        mailbox = Mailbox(max_sub_agents=3)
        mailbox.create_slot(Mailbox.COORDINATOR_ID)

        coord_registry = ToolRegistry()
        if self._tool_registry is not None:
            for tool_name in self._tool_registry.list_tools():
                tool = self._tool_registry.get_tool(tool_name)
                if tool is not None:
                    coord_registry.register_instance(tool)
        coord_registry.register_instance(CreateSubAgentTool())
        coord_registry.register_instance(CollectResultsTool())

        from app.agent.react_agent import ReActAgent
        coordinator = ReActAgent(
            tool_registry=coord_registry,
            memory_manager=self._memory_manager,
        )

        orig_call_tool = coordinator._call_tool
        async def patched_call_tool(tool_name, tool_input, context):
            tool_input["mailbox"] = mailbox
            tool_input["global_registry"] = self._tool_registry
            return await orig_call_tool(tool_name, tool_input, context)
        coordinator._call_tool = patched_call_tool

        return coordinator


    def _get_memory_context(self) -> dict:
        if self._memory_manager is None:
            return {}
        try:
            return self._memory_manager.get_context_for_qa() or {}
        except Exception:
            return {}





# 全局单例（API 层直接 import 使用）
# 工具和记忆管理器在 bootstrap 中注入
qa_workflow = QAWorkflow()
