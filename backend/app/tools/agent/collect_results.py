"""
CollectResultsTool - 收集子 Agent 结果工具

职责：Coordinator 通过此工具等待所有子 Agent 完成并收集结果。
  使用 asyncio.gather + timeout 实现并行执行和超时保护。
  部分子 Agent 失败不会影响整体的结果收集（graceful degradation）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.tools.base import BaseTool, ToolParameter, ToolParameterType, ToolResult
from app.tools.agent.mailbox import Mailbox, Message
from app.agent.react_agent import ReActAgent

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30  # 每个子 Agent 超时秒数


class CollectResultsTool(BaseTool):
    """
    收集子 Agent 结果工具 — Coordinator 用它等待并收集所有子 Agent 的结果。

    调用后会：
    1. 为每个待执行的子 Agent 启动异步 ReAct 执行
    2. 等待所有（或超时）
    3. 收集全部结果并返回
    """

    name: str = "collect_results"
    description: str = (
        "等待所有子 Agent 完成并收集它们的执行结果。"
        "会阻塞当前流程直到全部完成或超时。"
        "即使部分子 Agent 失败也能获取已完成的结果。"
    )
    parameters: list[ToolParameter] = [
        ToolParameter(
            name="task_ids",
            type=ToolParameterType.ARRAY,
            description="要收集结果的 task_id 列表（如 ['t1', 't2']）",
            required=True,
        ),
        ToolParameter(
            name="timeout_seconds",
            type=ToolParameterType.INTEGER,
            description="单个子 Agent 超时秒数，默认 30",
            required=False,
            default=_DEFAULT_TIMEOUT,
        ),
    ]

    async def execute(self, **kwargs) -> ToolResult:
        task_ids_raw: list = kwargs.get("task_ids") or []
        timeout_seconds: int = kwargs.get("timeout_seconds", _DEFAULT_TIMEOUT)
        mailbox: Mailbox | None = kwargs.get("mailbox")
        db = kwargs.get("db")
        user_id = kwargs.get("user_id")
        global_registry = kwargs.get("global_registry")

        if not task_ids_raw:
            return ToolResult(success=False, error="task_ids 不能为空")
        if mailbox is None:
            return ToolResult(success=False, error="mailbox 未传入")

        # ── 解析 task_ids ───────────────────────────────────────
        task_ids = [str(t).strip() for t in task_ids_raw if str(t).strip()]

        # ── 收集结果 ────────────────────────────────────────────
        results: dict[str, dict] = {}

        async def run_sub_agent(task_id: str) -> tuple[str, dict]:
            sub_agent_id = f"sub_{task_id}"

            # 从 mailbox 读取任务
            task_msg = mailbox.pop_task(sub_agent_id)
            if task_msg is None:
                return task_id, {
                    "answer": "未找到任务",
                    "sources": [],
                    "status": "failed",
                    "error": "task message not found",
                }

            task_content = task_msg.content
            question = task_content.get("question", "")
            allowed_tools = task_content.get("allowed_tools", [])

            # 构建受限 ToolRegistry
            sub_registry = _build_filtered_registry(global_registry, allowed_tools)

            # 创建子 Agent
            sub_agent = ReActAgent(
                tool_registry=sub_registry,
                memory_manager=kwargs.get("memory_manager"),
            )

            # 子 Agent 用更保守的 MAX_ROUNDS（5轮）
            from app.agent.react_agent import MAX_ROUNDS as ORIGINAL_MAX
            import app.agent.react_agent as react_module
            saved_max = react_module.MAX_ROUNDS
            react_module.MAX_ROUNDS = 5

            try:
                result = await sub_agent.run(
                    db=db,
                    user_id=user_id,
                    input_data={
                        "question": question,
                        "history": [],
                        "slow_router_result": {"path": "react", "reason": "sub-agent"},
                    },
                )
                data = result.get("data") or {}
                return task_id, {
                    "answer": data.get("answer", ""),
                    "sources": data.get("sources", []),
                    "status": result.get("status", "success"),
                    "error": None,
                }
            except Exception as e:
                logger.warning("sub_agent %s failed: %s", task_id, e)
                return task_id, {
                    "answer": "",
                    "sources": [],
                    "status": "failed",
                    "error": str(e),
                }
            finally:
                react_module.MAX_ROUNDS = saved_max

        # ── 并行执行（超时不抛异常）────────────────────────────
        tasks = [run_sub_agent(tid) for tid in task_ids]
        try:
            completed = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=max(timeout_seconds * len(task_ids), 30),
            )
        except asyncio.TimeoutError:
            # 整体超时 → 把尚未完成的标记为 failed
            ids_done = set(results.keys())
            for tid in task_ids:
                if tid not in ids_done:
                    results[tid] = {
                        "answer": "",
                        "sources": [],
                        "status": "failed",
                        "error": "timeout",
                    }
            return ToolResult(success=True, data={"results": results, "completed": len(results)})

        # ── 解析结果 ────────────────────────────────────────────
        for item in completed:
            if isinstance(item, Exception):
                # 某个子 Agent 整体异常，跳过
                continue
            if isinstance(item, tuple) and len(item) == 2:
                tid, r = item
                results[tid] = r

        # 填充未完成的（理论上不会，但保底）
        for tid in task_ids:
            if tid not in results:
                results[tid] = {"answer": "", "sources": [], "status": "failed", "error": "unknown"}

        # ── 清空推送进来的 result 消息（防止重复收集）────────────
        mailbox.clear_results_for(Mailbox.COORDINATOR_ID)

        return ToolResult(
            success=True,
            data={
                "results": results,
                "total": len(results),
                "success_count": sum(1 for r in results.values() if r.get("status") == "success"),
            },
        )


def _build_filtered_registry(source_registry: Any, allowed_tools: list[str]) -> Any:
    """从全局 registry 构建一个只包含允许工具的受限 registry。"""
    from app.tools.registry import ToolRegistry
    registry = ToolRegistry()
    for tool_name in allowed_tools:
        tool_instance = source_registry.get_tool(tool_name)
        if tool_instance is not None:
            registry.register_instance(tool_instance)
    return registry
