"""
SlowRouter - Slow 链路二级路由器

职责：所有进入 slow 路径的请求，再判断走哪条执行路径：
  - react:       探索式，步骤数未知，每步单工具推进（默认）
  - plan:        任务结构清晰，可预先拆解为固定步骤（3-7步）
  - multi_agent: 需并行扇出大量记录 或 多角色分工

设计原则（对齐 docs/routing_spec.md + phase_all_development_plan.md Phase 3）：
  用一次轻量 LLM 调用判定任务结构（不用纯规则，因为结构比意图更难规则化）。
  LLM 失败 → 降级到 react（默认值，无损失）。
  react 是默认值，接口从 Phase 3-A 就定好，Plan/Multi-Agent 后续填实现。

============================================================
内部处理流程:
============================================================

[步骤1] 接收输入
  user_message: str       # 原始用户问题
  memory_context: dict    # 轻量上下文（最近对话+活跃目标），可为空

[步骤2] LLM 轻量判定
  调 parse_json(SLOW_ROUTER_SCHEMA) 判定任务结构：
    - react:       步骤数未知，探索式，每步单工具推进
    - plan:        任务可预先列出固定步骤（3-7步），执行顺序固定
    - multi_agent: 需并行处理大量记录 OR 需多个独立角色协作

[步骤3] 失败降级
  LLM 不可用 / 解析失败 / 结果非法 → decided_by=fallback, path=react

[步骤4] 返回 SlowRouterResult
  path: "react" | "plan" | "multi_agent"
  reason: str
  decided_by: "llm" | "fallback"

============================================================
测试要点:
  1. "我昨天记了啥" → react（单轮检索，探索式）
  2. "帮我找所有Python相关笔记" → react（多轮探索）
  3. "对比我记的两个健身方案" → plan（固定步骤：取A→取B→比较）
  4. "制定我下个月的学习计划" → plan（固定步骤）
  5. "生成我这个月的学习月报" → multi_agent（大量记录并行）
  6. LLM 不可用 → react（fallback，decided_by=fallback）
  7. LLM 返回非法值 → react（fallback）
============================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


# ──────────────────────────────────────────────────────────────────
# LLM 判定 Schema
# ──────────────────────────────────────────────────────────────────

_SLOW_ROUTER_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "enum": ["react", "plan", "multi_agent"],
            "description": (
                "react: 探索式，步骤数未知，每步单工具推进（默认）; "
                "plan: 任务结构固定，可预先列出3-7个步骤; "
                "multi_agent: 需并行处理大量记录或多角色分工"
            ),
        },
        "reason": {
            "type": "string",
            "description": "判定理由，简短说明为什么选择这条路径",
        },
    },
    "required": ["path"],
}

_SLOW_ROUTER_PROMPT = """你是一个任务结构分析器。根据用户问题，判断应该走哪条执行路径。

三条路径的判定标准：

react（默认，探索式）：
- 步骤数不确定，需要边探索边决定下一步
- 单条/少量记录查询（"我记过妈妈生日吗"、"上周的学习记录"）
- 需要先检索再决定是否继续的场景

plan（固定步骤）：
- 任务结构清晰，可以预先列出3-7个固定步骤
- 典型场景：对比两个对象（取A→取B→对比）、制定计划（检索现状→分析→生成计划）
- 步骤之间有明确的依赖关系

multi_agent（并行扇出）：
- 需要同时处理大量独立的记录（月报/年报/全量分析）
- 或需要多个独立角色分工协作（一个负责数据，一个负责分析，一个负责写作）

疑问时默认选 react。

用户问题：{user_message}

用户上下文（可能为空）：{memory_context}
"""

_VALID_PATHS = frozenset({"react", "plan", "multi_agent"})

# ──────────────────────────────────────────────────────────────────
# 规则词表（对照 routing_spec.md v3.0）
# 只枚举明确的 plan/multi_agent 信号；其余默认 react。
# ──────────────────────────────────────────────────────────────────

# plan 信号：任务结构清晰、可预先列出固定步骤
_PLAN_KEYWORDS = (
    "对比", "比较", "制定计划", "拟定计划", "生成计划",
    "步骤", "分步", "怎么做", "如何做",
)

# multi_agent 信号：大量记录并行扇出 / 多角色协作
_MULTI_AGENT_KEYWORDS = (
    "月报", "年报", "周报", "全量分析", "汇总分析",
    "所有记录", "全部记录", "统计所有",
)


# ──────────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────────

@dataclass
class SlowRouterResult:
    """Slow 二级路由决策结果"""
    path: str = "react"               # "react" | "plan" | "multi_agent"
    reason: str = ""
    decided_by: str = "llm"           # "llm" | "fallback"

    @property
    def is_react(self) -> bool:
        return self.path == "react"

    @property
    def is_plan(self) -> bool:
        return self.path == "plan"

    @property
    def is_multi_agent(self) -> bool:
        return self.path == "multi_agent"

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "reason": self.reason,
            "decided_by": self.decided_by,
        }


# ──────────────────────────────────────────────────────────────────
# SlowRouter
# ──────────────────────────────────────────────────────────────────

class SlowRouter:
    """
    Slow 链路二级路由器。

    用法:
        slow_router = SlowRouter()
        result = await slow_router.route("对比我记的两个健身方案")
        # → SlowRouterResult(path="plan", decided_by="llm")

    为便于测试，LLM 调用通过 `llm_parse_json` 注入:
        router = SlowRouter(llm_parse_json=fake_fn)
    fake_fn 签名: (prompt: str, schema: dict) -> dict | None
    """

    def __init__(
        self,
        llm_parse_json: Optional[Callable[..., Optional[dict]]] = None,
    ):
        self._llm_parse_json = llm_parse_json

    async def route(
        self,
        user_message: str,
        memory_context: Optional[dict] = None,
    ) -> SlowRouterResult:
        """判定 slow 请求应走哪条执行路径。"""
        text = (user_message or "").strip()
        if not text:
            return SlowRouterResult(path="react", reason="空输入，默认 react", decided_by="fallback")

        # 规则层：先用关键词判断明确的 plan/multi_agent 特征
        rule_result = self._resolve_by_rules(text)
        if rule_result is not None:
            return rule_result

        # 规则无法判断时才调 LLM（仅对边界情况）
        return self._resolve_by_llm(text, memory_context or {})

    # ------------------------------------------------------------------
    # 规则层（零 LLM，零延迟）
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_by_rules(text: str) -> Optional["SlowRouterResult"]:
        """纯规则判断，命中则返回结果，未命中返回 None（交给 LLM）。"""
        if any(kw in text for kw in _MULTI_AGENT_KEYWORDS):
            return SlowRouterResult(
                path="multi_agent",
                reason="大量记录/并行任务，规则判定",
                decided_by="rule",
            )
        if any(kw in text for kw in _PLAN_KEYWORDS):
            return SlowRouterResult(
                path="plan",
                reason="固定步骤任务，规则判定",
                decided_by="rule",
            )
        # 其他一律默认 react，不需要 LLM
        return SlowRouterResult(
            path="react",
            reason="默认走 ReAct，规则判定",
            decided_by="rule",
        )

    # ------------------------------------------------------------------
    # LLM 判定层
    # ------------------------------------------------------------------
    def _resolve_by_llm(self, text: str, memory_context: dict) -> SlowRouterResult:
        parse_json = self._get_parse_json()
        if parse_json is None:
            return SlowRouterResult(
                path="react",
                reason="LLM 不可用，降级默认 react",
                decided_by="fallback",
            )

        ctx_str = self._format_context(memory_context)
        prompt = _SLOW_ROUTER_PROMPT.format(
            user_message=text,
            memory_context=ctx_str or "（无上下文）",
        )

        try:
            data = parse_json(prompt=prompt, schema=_SLOW_ROUTER_SCHEMA)
        except Exception:
            data = None

        if not data or data.get("path") not in _VALID_PATHS:
            return SlowRouterResult(
                path="react",
                reason="LLM 返回无效，降级默认 react",
                decided_by="fallback",
            )

        return SlowRouterResult(
            path=data["path"],
            reason=str(data.get("reason") or "LLM 判定"),
            decided_by="llm",
        )

    def _get_parse_json(self) -> Optional[Callable[..., Optional[dict]]]:
        if self._llm_parse_json is not None:
            return self._llm_parse_json
        try:
            from app.services.llm_answer_service import llm_answer_service
            if not llm_answer_service.is_available():
                return None
            return llm_answer_service.parse_json
        except Exception:
            return None

    @staticmethod
    def _format_context(ctx: dict) -> str:
        """把 memory_context 压缩成一段简短文字供 LLM 参考。"""
        if not ctx:
            return ""
        parts: list[str] = []
        if ctx.get("recent_turns"):
            turns = ctx["recent_turns"][-3:]  # 只取最近3轮
            turns_str = " | ".join(
                f"{t.get('role','?')}: {str(t.get('content',''))[:40]}"
                for t in turns
            )
            parts.append(f"最近对话: {turns_str}")
        if ctx.get("active_goals"):
            goals = ctx["active_goals"][:2]
            parts.append(f"活跃目标: {', '.join(str(g) for g in goals)}")
        return "; ".join(parts)
