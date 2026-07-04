"""
CreateSubAgentTool - 创建子 Agent 工具

职责：Coordinator 通过此工具创建一个子 Agent 来处理独立子任务。
  子 Agent 拥有独立的 ReAct 循环和受限制的工具权限。

权限设计：
  - Coordinator 在 allowed_tools 参数中指定子 Agent 可用的工具
  - create_sub_agent / collect_results 会被代码层强制过滤掉（硬约束）
  - 子 Agent 数 ≥ 3 时返回错误（上限保护）

用法（在 Coordinator ReAct 循环中）:
  coordinator 的 system_prompt:
    可用工具: [create_sub_agent, collect_results, hybrid_search, ...]
  → LLM 调用 create_sub_agent(
      task_id="t1",
      question="分析这个月学习类笔记的主题",
      allowed_tools=["hybrid_search", "time_resolver"],
    )
  → ToolResult(success=True, data={"task_id": "t1", "status": "created"})
  → 后续调用 collect_results 并行执行并收集结果
"""
from __future__ import annotations

from app.tools.base import BaseTool, ToolParameter, ToolParameterType, ToolResult
from app.tools.agent.mailbox import Mailbox, Message

# 硬约束：这些工具不可分配给子 Agent（代码层过滤，不信任 LLM）
_FORBIDDEN_SUB_AGENT_TOOLS = {"create_sub_agent", "collect_results"}

# 子 Agent 的 MAX_ROUNDS（比顶层 ReAct 的 10 轮更保守）
_SUB_AGENT_MAX_ROUNDS = 5


class CreateSubAgentTool(BaseTool):
    """
    创建子 Agent 工具 — Coordinator 通过它创建子 Agent。

    子 Agent 是独立的 ReActAgent，拥有受限制的工具集。
    """

    name: str = "create_sub_agent"
    description: str = (
        "创建一个子 Agent 来处理独立的子任务。"
        "子 Agent 会并行执行，不会阻塞 Coordinator。"
        "每个子 Agent 只能使用你指定的工具。"
    )
    parameters: list[ToolParameter] = [
        ToolParameter(
            name="task_id",
            type=ToolParameterType.STRING,
            description="子任务唯一标识，后续用 collect_results 收集结果",
            required=True,
        ),
        ToolParameter(
            name="question",
            type=ToolParameterType.STRING,
            description="子 Agent 的执行目标",
            required=True,
        ),
        ToolParameter(
            name="context",
            type=ToolParameterType.STRING,
            description="任务背景信息（可选）",
            required=False,
        ),
        ToolParameter(
            name="allowed_tools",
            type=ToolParameterType.ARRAY,
            description="子 Agent 可用的工具名列表。"
                         f"可用选项: hybrid_search, time_resolver, fact_extractor, "
                         f"relation_finder, web_search, weather。"
                         f"create_sub_agent 和 collect_results 不可用于子 Agent。",
            required=True,
        ),
    ]

    async def execute(self, **kwargs) -> ToolResult:
        task_id: str = (kwargs.get("task_id") or "").strip()
        question: str = (kwargs.get("question") or "").strip()
        context_str: str = (kwargs.get("context") or "").strip()
        allowed_tools_raw: list = kwargs.get("allowed_tools") or []
        mailbox: Mailbox | None = kwargs.get("mailbox")
        global_registry = kwargs.get("global_registry")

        # ── 校验 ────────────────────────────────────────────────
        if not task_id:
            return ToolResult(success=False, error="task_id 不能为空")
        if not question:
            return ToolResult(success=False, error="question 不能为空")
        if mailbox is None:
            return ToolResult(success=False, error="mailbox 未传入")
        if global_registry is None:
            return ToolResult(success=False, error="global_registry 未传入")

        # ── 上限检查 ────────────────────────────────────────────
        if mailbox.count_sub_agents() >= mailbox.max_sub_agents():
            return ToolResult(
                success=False,
                error=f"已达子 Agent 上限({mailbox.max_sub_agents()}个)",
            )

        # ── 过滤 forbidden tools ────────────────────────────────
        allowed_tools = [
            t for t in allowed_tools_raw
            if isinstance(t, str) and t not in _FORBIDDEN_SUB_AGENT_TOOLS
        ]
        # 同时确保每个工具在全局注册表中存在
        existing_tools = []
        for t in allowed_tools:
            tool_instance = global_registry.get_tool(t) if hasattr(global_registry, "get_tool") else None
            if tool_instance is not None:
                existing_tools.append(t)

        # ── 创建子 Agent 信箱槽位 ──────────────────────────────
        sub_agent_id = f"sub_{task_id}"
        mailbox.create_slot(sub_agent_id)

        # ── 把任务写入子 Agent 的 inbox ─────────────────────────
        task_msg = Message(
            msg_id=f"task_{task_id}",
            from_agent=Mailbox.COORDINATOR_ID,
            to_agent=sub_agent_id,
            type="task",
            task_id=task_id,
            content={
                "question": question,
                "context": context_str,
                "allowed_tools": existing_tools,
            },
        )
        mailbox.send(Mailbox.COORDINATOR_ID, sub_agent_id, task_msg)

        return ToolResult(
            success=True,
            data={
                "task_id": task_id,
                "sub_agent_id": sub_agent_id,
                "status": "created",
                "allowed_tools": existing_tools,
            },
        )
