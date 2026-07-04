"""
Router - 意图路由器 (Fast / Slow 分流)

职责：判断请求走哪条链路。

设计原则（对齐 docs/routing_spec.md v3.0）：
  核心判断维度只有一个：**这个问题需要读用户的记录吗？**
    - 需要 → slow（统一走 ReAct，从单条查到跨记录分析）
    - 不需要 → fast（问候/系统问答 + 外部工具查询）

fast 只有两类，边界极清晰：
  1. 系统级交互：你好/谢谢/你是谁/你能干什么 — 不碰记录，模板/LLM 直答
  2. 外部信息查询：天气/搜索/汇率 — 答案来自外部 API，不碰记录
     携带固定工具：WeatherTool / WebSearchTool

slow 是默认值 — 不需要 LLM 兜底，规则第3条直接给 slow：
  任何没有命中 fast 信号的输入，全部默认走 ReAct，不产生歧义。

============================================================
内部处理流程（v3.0 极简版）:
============================================================

[步骤1] 接收 user_message: str

[步骤2] 规则判定（纯规则，零 LLM，零延迟）
  1. 空输入 → fast
  2. 命中问候/系统词 → fast（系统交互）
  3. 命中外部查询词 → fast（外部工具，携带 WeatherTool/WebSearchTool）
  4. 其他一切 → slow（默认，走 ReAct + RAG）

[步骤3] 返回 RouterResult
  complexity / reason / suggested_tools / decided_by

============================================================
测试要点:
  1. "你好" → fast, decided_by=rule
  2. "北京今天天气" → fast, suggested_tools=[weather]
  3. "搜一下React教程" → fast, suggested_tools=[web_search]
  4. "我昨天记了啥" → slow（默认）
  5. "今天心情不好" → slow（情绪也走ReAct，能感知记录背景）
  6. "分析我这个月学习" → slow
  7. 任何没命中 fast 词表的 → slow（默认）
============================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


# ──────────────────────────────────────────────────────────────────
# 规则词表 (对齐 docs/routing_spec.md v3.0)
# 设计：枚举 fast 的明确信号，其他全部默认 slow。
# ──────────────────────────────────────────────────────────────────

# fast 类型1: 系统级交互 — 问候/告别/询问系统能力
_FAST_SYSTEM_KEYWORDS = (
    # 问候/告别
    "你好", "您好", "谢谢", "感谢", "再见", "晚安", "拜拜",
    "嗨", "hello", "hi", "早上好", "早安", "晚好",
    # 系统问答
    "你是谁", "你叫什么", "你是什么", "你能做什么", "你能帮我做什么",
    "你能干什么", "你有什么功能", "怎么使用",
    "什么模型", "哪个模型", "用的什么", "什么版本",
    # 简单确认（对话推进，不碰记录）
    "在吗", "ok", "好的", "嗯嗯", "收到",
)

# fast 类型2: 外部信息查询 — 答案来自外部 API，不碰用户记录
_FAST_EXTERNAL_KEYWORDS = (
    # 天气
    "天气", "气温", "温度", "下雨", "下雪", "晴天", "会不会下雨",
    # 搜索（纯外网，不含个人记录）
    "搜一下", "搜索一下", "帮我搜", "查一下", "查查",
    # 时间/日期（系统时间，不是查记录）
    "现在几点", "今天几号", "今天是什么日期", "今天是星期", "星期几", "几号了",
    # 汇率/股票等外部数据
    "汇率", "股价",
)

# 个人域信号：如果外部查询词和这些词同时出现，说明用户是在查自己的记录而非外网
# 例："查一下我记的那条计划" → 有"查一下"但也有"记的" → 应走 slow
_PERSONAL_DOMAIN_OVERRIDE = (
    "我记的", "我记过", "我写的", "我的记录", "我的笔记", "我的日记",
    "有没有记", "记了没", "记过", "备忘", "待办",
    "记了几条", "记了几篇", "记了多少",
)

# fast 各类携带的工具提示（供 QA Agent 选择）
_FAST_EXTERNAL_TOOL_MAP = {
    "weather": ("天气", "气温", "温度", "下雨", "下雪", "晴天", "会不会下雨"),
    "web_search": ("搜一下", "搜索一下", "帮我搜", "查一下", "查查", "汇率", "股价"),
    "datetime": ("现在几点", "今天几号", "今天是什么日期", "今天是星期", "星期几", "几号了"),
}

# slow 是默认值，不需要词表
# 任何没有命中 fast 词表的输入，全部默认 slow

# LLM schema（保留备用，当前路由纯规则不调 LLM）
_ROUTER_SCHEMA = {
    "type": "object",
    "properties": {
        "complexity": {
            "type": "string",
            "enum": ["fast", "slow"],
            "description": "fast=问候/外部查询(不碰记录); slow=涉及个人记录",
        },
        "reason": {"type": "string"},
        "suggested_tools": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["complexity"],
}

_ROUTER_PROMPT_TEMPLATE = """请判断用户输入应该走哪条处理链路。

判定标准：
- fast：问候/系统问答/外部工具查询(天气/搜索)，完全不碰用户个人记录。
- slow：任何需要查看/检索/分析用户个人记录的请求（默认值）。

用户输入：{user_message}
"""


@dataclass
class RouterResult:
    """路由决策结果"""
    complexity: str = "fast"               # "fast" | "slow"
    reason: str = ""
    suggested_tools: list[str] = field(default_factory=list)
    decided_by: str = "rule"               # "rule" | "llm" | "fallback"

    @property
    def is_fast(self) -> bool:
        return self.complexity == "fast"

    @property
    def is_slow(self) -> bool:
        return self.complexity == "slow"

    def to_dict(self) -> dict:
        return {
            "complexity": self.complexity,
            "reason": self.reason,
            "suggested_tools": self.suggested_tools,
            "decided_by": self.decided_by,
        }


class Router:
    """
    意图路由器

    用法：
        router = Router()                       # 默认用 llm_answer_service
        result = router.route("你好")           # → RouterResult(fast)

    为便于测试，分类用的 LLM 调用通过 `llm_parse_json` 注入：
        router = Router(llm_parse_json=fake_fn)
    fake_fn 签名: (prompt: str, schema: dict) -> dict | None
    """

    def __init__(self, llm_parse_json: Optional[Callable[..., Optional[dict]]] = None):
        self._llm_parse_json = llm_parse_json

    def route(self, user_message: str) -> RouterResult:
        # [步骤1] 接收输入
        text = (user_message or "").strip()

        # 空输入兜底
        if not text:
            return RouterResult(complexity="fast", reason="空输入，默认 fast", decided_by="rule")

        # [步骤2] 规则判定（纯规则，永远返回结果，不调 LLM）
        return self._resolve_by_rules(text)

    # ------------------------------------------------------------------
    # 规则层 (对齐 docs/routing_spec.md v3.0)
    # 极简三条：fast 信号枚举，其他默认 slow，不需要 LLM 兜底
    # ------------------------------------------------------------------
    def _resolve_by_rules(self, text: str) -> RouterResult:
        """纯规则，永远返回 RouterResult，不再需要 LLM 兜底。"""

        # ── 规则1: 系统级交互 → fast ────────────────────────
        if any(kw in text for kw in _FAST_SYSTEM_KEYWORDS):
            return RouterResult(
                complexity="fast",
                reason="问候/系统问答，不碰用户记录",
                decided_by="rule",
            )

        # ── 规则2: 外部信息查询 → fast + 工具提示 ───────────
        # 但如果同时含有个人域信号（"查一下我记的..."），则覆盖为 slow
        has_personal_override = any(kw in text for kw in _PERSONAL_DOMAIN_OVERRIDE)
        suggested: list[str] = []
        for tool_name, keywords in _FAST_EXTERNAL_TOOL_MAP.items():
            if any(kw in text for kw in keywords):
                suggested.append(tool_name)
        if suggested and not has_personal_override:
            return RouterResult(
                complexity="fast",
                reason="外部信息查询，不碰用户记录",
                suggested_tools=suggested,
                decided_by="rule",
            )

        # ── 规则3: 默认 slow ────────────────────────────────
        # 任何没命中 fast 的输入，全部走 ReAct（带 RAG）
        return RouterResult(
            complexity="slow",
            reason="默认走 ReAct，可能需要访问用户记录",
            decided_by="rule",
        )

    # ------------------------------------------------------------------
    # LLM 层
    # ------------------------------------------------------------------
    def _resolve_by_llm(self, text: str) -> RouterResult:
        parse_json = self._get_parse_json()
        if parse_json is None:
            return RouterResult(
                complexity="fast",
                reason="LLM 不可用，规则无法判定，退回默认 fast",
                decided_by="fallback",
            )

        prompt = _ROUTER_PROMPT_TEMPLATE.format(user_message=text)
        try:
            data = parse_json(prompt=prompt, schema=_ROUTER_SCHEMA)
        except Exception:
            data = None

        if not data or data.get("complexity") not in ("fast", "slow"):
            return RouterResult(
                complexity="fast",
                reason="LLM 输出无效，退回默认 fast",
                decided_by="fallback",
            )

        tools = data.get("suggested_tools") or []
        if not isinstance(tools, list):
            tools = []

        return RouterResult(
            complexity=data["complexity"],
            reason=str(data.get("reason") or "LLM 判定"),
            suggested_tools=[str(t) for t in tools],
            decided_by="llm",
        )

    def _get_parse_json(self) -> Optional[Callable[..., Optional[dict]]]:
        if self._llm_parse_json is not None:
            return self._llm_parse_json
        from app.services.llm_answer_service import llm_answer_service
        if not llm_answer_service.is_available():
            return None
        return llm_answer_service.parse_json
