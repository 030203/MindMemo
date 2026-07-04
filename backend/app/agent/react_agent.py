"""
ReAct Agent - Slow 链路默认执行引擎

职责：处理 SlowRouter 判定为 react 的请求，动态决策每一步。
  Thought → Action → Observation 循环，直到能给出完整回答。

设计原则（对齐 phase_all_development_plan.md Phase 3-A）：
  - 不需要预先规划，边推理边决定下一步（对比 Planner 的固定步骤）
  - 工具调用通过 OpenAI function_call 协议（LLMClient.function_call）
  - MAX_ROUNDS 防死循环，超限返回 partial 状态
  - 来源引用：从工具返回中提取 memory_id，填入 sources

============================================================
内部处理流程:
============================================================

[步骤1] 接收输入
  input_data = {
    "question": str,                  # 用户问题
    "slow_router_result": dict,       # 来自 SlowRouter（可选）
    "history": list[dict],            # 最近对话历史（可选）
  }

[步骤2] _pre_execute — 加载记忆上下文
  memory_manager.get_context_for_qa() → recent_turns + recent_memories
  存入 context.variables["memory_context"]

[步骤3] execute — ReAct 主循环

  messages = [system_prompt, user_message]
  tool_schemas = tool_registry.list_tool_schemas()  # OpenAI function 格式

  for round_num in range(MAX_ROUNDS):

    [3.1] 调 LLMClient.function_call(messages, tools=tool_schemas)
          返回: {"type": "tool_call", "name": ..., "arguments": ...}
                 或 {"type": "text", "content": "最终回答"}

    [3.2] 如果 type=text → 这就是最终回答，break

    [3.3] 如果 type=tool_call:
          tool_result = await _call_tool(name, args, context)
          把 tool_result 追加到 messages（role=tool）
          记录 Thought / Action / Observation 到 trajectory

    [3.4] 超过 MAX_ROUNDS → status=partial，返回最后一轮的文本

[步骤4] _post_execute — 写回 WorkingMemory
  mm.working.add_turn("user", question)
  mm.working.add_turn("assistant", answer)

[步骤5] 返回结果
  {
    "status": "success" | "partial" | "no_tool_registry",
    "data": {
      "answer": str,
      "sources": [{"memory_id": str, "title": str}],
      "tool_calls_made": int,
      "rounds": int,
    }
  }

============================================================
测试要点:
  1. 简单查询(1轮): 工具返回结果 → LLM 生成答案 → status=success
  2. 多轮探索: 工具调两次 → 汇总回答
  3. MAX_ROUNDS 保护: 工具永远返回"继续" → 10轮后 status=partial
  4. 无记录: 工具返回空 → 诚实回答"未找到"，不编造
  5. 来源引用: sources 包含实际用到的 memory_id
  6. 工具调用失败: graceful 处理，继续循环
  7. 无 tool_registry → status=no_tool_registry（降级到 QA Agent 处理）
============================================================
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.agent.base import AgentContext, BaseAgent


# ──────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────

MAX_ROUNDS = 10  # ReAct 最大轮数，防止死循环

_SYSTEM_PROMPT = """你是 MindMemo 的个人记忆助手，帮助用户查找、分析和整理他们自己记录的内容。

你有以下工具可以使用：
{tool_descriptions}

用户的记忆上下文：
{memory_context}

今天的日期：{current_date}

工作原则：
1. 优先使用工具检索用户的真实记录，不要凭空编造
2. 如果搜索无结果，诚实告知用户"没有找到相关记录"
3. hybrid_search 只返回摘要和正文预览片段。当用户要求总结、分析或详细讲解
   某条记录的完整内容（如整篇文章、简历、长笔记）时，务必用搜索结果里的
   memory_id 调用 read_memory 获取完整正文后再作答，不要只凭预览和标签下结论。
3.1 关键：记录正文里的相对时间（"明天""下周三""三天后"）是相对**记录时刻**说的，
    不是相对今天。每条记忆都带 recorded_at（记录时刻）字段，遇到相对时间必须以
    recorded_at 为锚点换算成绝对日期，再结合"今天的日期"判断它是否还在未来。
    例：recorded_at=7月2日、正文写"明天上午开会" → 会议 = 7月3日上午；若今天是
    7月4日，说明这场会已经过去了，要如实说明，而不是照抄"明天上午"。
    回答涉及时间的记录时，标明【记录于 X，据此推算为 具体日期】。
4. 关于待办和提醒：问到"待办""提醒""快到期"时，必须用 list_tasks 工具查询，
   不要用 hybrid_search 猜测。回答时遵守以下规则：
   - 每条待办都要标明【记录于 X】和【截止 Y，还剩 Z 天】；逾期的写【已逾期 Z 天】。
     天数直接用工具返回的 days_left（负数表示逾期），不要自己重新算日期。
   - 逾期待办（overdue_todos）单独归成一组，用"⚠️ 已逾期"之类的小标题集中提示。
   - 未来待办（upcoming_todos）另成一组，按剩余天数从近到远列出。
   - 提醒只列未来的（upcoming_reminders），已经过去的提醒不要提。
   - 一次性把记录时间、截止时间、剩余/逾期天数都给全，不要让用户二次追问。
   - 无 deadline 的待办（days_left 为 None）照常列出，注明"未设截止时间"。
5. 回答要简洁、自然、有温度，像一个了解用户的助手
6. 引用记录时说明来源（标题/时间）
"""

_FALLBACK_ANSWER = "抱歉，无法处理您的请求，请稍后重试。"


class ReActAgent(BaseAgent):
    """
    ReAct Agent — slow 路径的默认执行引擎。

    用法:
        agent = ReActAgent(
            memory_manager=mm,
            tool_registry=registry,
            llm_function_call=fake_fn,   # 测试时注入
        )
        result = await agent.run(db, user_id, {"question": "我昨天记了啥"})

    llm_function_call 签名:
        (messages: list[dict], tools: list[dict]) -> dict | None
        返回:
          {"type": "tool_call", "name": str, "arguments": dict}
          或 {"type": "text", "content": str}
          或 None（LLM 不可用）
    """

    def __init__(
        self,
        memory_manager: Optional[Any] = None,
        tool_registry: Optional[Any] = None,
        llm_function_call: Optional[Callable[..., Optional[dict]]] = None,
    ):
        super().__init__(
            name="react_agent",
            description="探索式多轮推理，slow 路径默认执行引擎",
            memory_manager=memory_manager,
            tool_registry=tool_registry,
        )
        self._llm_function_call = llm_function_call

    # ------------------------------------------------------------------
    # _pre_execute: 加载记忆上下文
    # ------------------------------------------------------------------
    async def _pre_execute(
        self,
        db: Session,
        user_id: UUID,
        input_data: dict[str, Any],
        context: AgentContext,
    ) -> None:
        memory_context: dict = {}
        if self.memory_manager is not None:
            try:
                memory_context = self.memory_manager.get_context_for_qa() or {}
            except Exception:
                memory_context = {}
        context.set_variable("memory_context", memory_context)

    # ------------------------------------------------------------------
    # execute: ReAct 主循环
    # ------------------------------------------------------------------
    async def execute(
        self,
        db: Session,
        user_id: UUID,
        input_data: dict[str, Any],
        context: AgentContext,
    ) -> dict[str, Any]:
        question = (input_data.get("question") or "").strip()
        history: list[dict] = input_data.get("history") or []

        if not question:
            return {
                "status": "success",
                "data": {"answer": "请问有什么可以帮你的？", "sources": [], "tool_calls_made": 0, "rounds": 0},
            }

        # ── 无工具注册时降级 ──────────────────────────────────────
        if not self.tool_registry:
            return {
                "status": "no_tool_registry",
                "data": {"answer": _FALLBACK_ANSWER, "sources": [], "tool_calls_made": 0, "rounds": 0},
            }

        # ── 获取 LLM 调用函数 ─────────────────────────────────────
        fn_call = self._get_llm_function_call()
        if fn_call is None:
            return {
                "status": "success",
                "data": {"answer": _FALLBACK_ANSWER, "sources": [], "tool_calls_made": 0, "rounds": 0},
            }

        # ── 构造工具 schema 列表 ──────────────────────────────────
        tool_schemas = self.tool_registry.list_tool_schemas()

        # ── 构造 system prompt ────────────────────────────────────
        memory_context = context.get_variable("memory_context", {})
        from datetime import datetime as _dt
        system_content = _SYSTEM_PROMPT.format(
            tool_descriptions=self._format_tool_descriptions(tool_schemas),
            memory_context=self._format_memory_context(memory_context),
            current_date=_dt.now().strftime("%Y-%m-%d (%A)"),
        )

        # ── Plan 注入 ──────────────────────────────────────────
        # 如果 input_data 中带有 plan，格式化为建议步骤附加在 system prompt 末尾
        plan = input_data.get("plan")
        if plan is not None:
            plan_hint = self._format_plan_hint(plan)
            if plan_hint:
                system_content += plan_hint

        # ── 构造初始 messages ─────────────────────────────────────
        messages: list[dict] = [{"role": "system", "content": system_content}]
        for turn in history[-5:]:  # 最多保留最近 5 轮历史
            if turn.get("role") in ("user", "assistant") and turn.get("content"):
                messages.append({"role": turn["role"], "content": str(turn["content"])})
        messages.append({"role": "user", "content": question})

        # ── ReAct 主循环 ──────────────────────────────────────────
        sources: list[dict] = []
        final_answer: str = ""
        round_num = 0

        for round_num in range(MAX_ROUNDS):
            try:
                llm_result = fn_call(messages=messages, tools=tool_schemas)
            except Exception:
                llm_result = None

            if llm_result is None:
                break

            result_type = llm_result.get("type", "text")

            # ── 终止：LLM 给出最终回答 ─────────────────────────
            if result_type == "text":
                final_answer = llm_result.get("content", "").strip()
                context.add_thought(f"Round {round_num + 1}: 生成最终回答")
                break

            # ── 继续：LLM 决定调工具 ───────────────────────────
            if result_type == "tool_call":
                tool_name = llm_result.get("name", "")
                tool_args = llm_result.get("arguments") or {}
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except Exception:
                        tool_args = {}

                context.add_thought(
                    f"Round {round_num + 1}: 调用工具 {tool_name}({tool_args})"
                )

                # 注入 db / user_id 供工具使用
                tool_args.setdefault("db", db)
                tool_args.setdefault("user_id", user_id)

                try:
                    tool_result = await self._call_tool(tool_name, tool_args, context)
                    observation = self._serialize_tool_result(tool_result)
                    # 提取来源
                    self._extract_sources(tool_result, sources)
                except Exception as e:
                    observation = f"工具调用失败: {e}"

                # 把 assistant message（含 tool_call）追加到 messages 链
                assistant_msg = llm_result.get("_assistant_msg") or {
                    "role": "assistant", "content": None,
                }
                messages.append(assistant_msg)
                # 把 tool result 追加到 messages 链
                messages.append({
                    "role": "tool",
                    "tool_call_id": (
                        assistant_msg.get("tool_calls") or [{}]
                    )[0].get("id", ""),
                    "name": tool_name,
                    "content": observation,
                })

        else:
            # MAX_ROUNDS 触发
            return {
                "status": "partial",
                "data": {
                    "answer": final_answer or "处理超时，无法给出完整回答",
                    "sources": sources,
                    "tool_calls_made": len(context.tool_calls),
                    "rounds": MAX_ROUNDS,
                },
            }

        return {
            "status": "success",
            "data": {
                "answer": final_answer or _FALLBACK_ANSWER,
                "sources": sources,
                "tool_calls_made": len(context.tool_calls),
                "rounds": round_num + 1,
            },
        }

    # ------------------------------------------------------------------
    # _post_execute: 写回 WorkingMemory
    # ------------------------------------------------------------------
    async def _post_execute(
        self,
        db: Session,
        user_id: UUID,
        result: dict[str, Any],
        context: AgentContext,
    ) -> None:
        if self.memory_manager is None:
            return
        try:
            question = context.get_variable("question", "")
            answer = (result.get("data") or {}).get("answer", "")
            if question and answer:
                mm = self.memory_manager
                if hasattr(mm, "working") and hasattr(mm.working, "add_turn"):
                    mm.working.add_turn("user", question)
                    mm.working.add_turn("assistant", answer)
        except Exception:
            pass  # working memory 写入失败不影响主流程

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    def _get_llm_function_call(self) -> Optional[Callable[..., Optional[dict]]]:
        if self._llm_function_call is not None:
            return self._llm_function_call
        try:
            from app.services.llm_answer_service import llm_answer_service
            if not llm_answer_service.is_available():
                return None
            return llm_answer_service.function_call
        except Exception:
            return None

    @staticmethod
    def _format_tool_descriptions(schemas: list[dict]) -> str:
        if not schemas:
            return "（无可用工具）"
        lines = []
        for s in schemas:
            lines.append(f"- {s.get('name', '?')}: {s.get('description', '')}")
        return "\n".join(lines)

    @staticmethod
    def _format_memory_context(ctx: dict) -> str:
        if not ctx:
            return "（暂无上下文）"
        parts: list[str] = []
        turns = ctx.get("recent_turns") or []
        if turns:
            last = turns[-3:]
            parts.append("最近对话: " + " | ".join(
                f"{t.get('role','?')}: {str(t.get('content',''))[:50]}"
                for t in last
            ))
        goals = ctx.get("active_goals") or []
        if goals:
            parts.append(f"活跃目标: {', '.join(str(g) for g in goals[:2])}")
        return "; ".join(parts) or "（暂无上下文）"

    @staticmethod
    def _format_plan_hint(plan: Any) -> str:
        """把 Plan 对象格式化为建议步骤提示文本。"""
        # 支持 Plan dataclass 和 dict 两种输入
        if hasattr(plan, "to_hint_text"):
            return plan.to_hint_text()
        if isinstance(plan, dict):
            steps = plan.get("steps") or []
            if not steps:
                return ""
            lines = ["\n建议执行步骤（供参考，非强制顺序）:"]
            for s in steps:
                step_num = s.get("step", steps.index(s) + 1)
                desc = s.get("description", "")
                tool_name = s.get("tool_name")
                hint = s.get("hint", "")
                tool_txt = f" → 工具: {tool_name}" if tool_name else " → 纯LLM推理"
                hint_txt = f" ({hint})" if hint else ""
                lines.append(f"  {step_num}. {desc}{tool_txt}{hint_txt}")
            return "\n".join(lines)
        return ""

    @staticmethod
    def _serialize_tool_result(tool_result: Any) -> str:
        """把 ToolResult 序列化成可追加到 messages 的字符串。"""
        if tool_result is None:
            return "（工具返回空）"
        if hasattr(tool_result, "model_dump"):
            d = tool_result.model_dump()
            return json.dumps(d, ensure_ascii=False, default=str)
        if hasattr(tool_result, "__dict__"):
            return json.dumps(tool_result.__dict__, ensure_ascii=False, default=str)
        return str(tool_result)

    @staticmethod
    def _extract_sources(tool_result: Any, sources: list[dict]) -> None:
        """从工具结果中提取 memory_id / title，去重后追加到 sources。"""
        if tool_result is None:
            return
        data = None
        if hasattr(tool_result, "data"):
            data = tool_result.data
        elif isinstance(tool_result, dict):
            data = tool_result.get("data")

        if not data:
            return

        seen_ids: set[str] = {s.get("memory_id", "") for s in sources}

        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                mid = str(item.get("memory_id") or item.get("id") or "")
                if mid and mid not in seen_ids:
                    sources.append({
                        "memory_id": mid,
                        "title": str(item.get("title") or item.get("content", "")[:40]),
                    })
                    seen_ids.add(mid)
