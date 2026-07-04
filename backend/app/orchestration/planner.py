"""
Planner - 任务规划器（Phase 3-B）

职责：把用户的结构化任务拆解为固定步骤序列，注入给 ReAct。
  不强制 ReAct 按步执行，仅作为「建议执行顺序」提示。

设计原则：
  - 宽松注入：步骤以自然语言附加在 system_prompt 末尾，不新建执行器
  - Plan 生成失败 → 返回 None → 调用方降级为自由 ReAct（无损失）
  - Plan 步骤数限制 2~5，防止过度拆解
  - 工具名不存在 → 验证失败返回 None

============================================================
内部处理流程:
============================================================

[步骤1] 接收输入
  user_message: str
  tool_registry: ToolRegistry  # 获取可用工具列表

[步骤2] LLM 拆解
  调 parse_json(prompt=PLANNER_PROMPT, schema=PLAN_SCHEMA)

[步骤3] 验证
  - steps 非空，长度 2~5
  - 有 tool_name 的步骤，工具必须在 ToolRegistry 中存在
  - 验证失败 → 返回 None

[步骤4] 返回 Plan 或 None

[Plan 注入 ReAct]
  QAWorkflow 在调用 ReActAgent 前，把 plan 作为 input_data["plan"] 传入。
  ReActAgent 发现 input_data 有 plan 时，格式化步骤附加在 system_prompt 末尾。
============================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


# ──────────────────────────────────────────────────────────────────
# 数据结构
# ──────────────────────────────────────────────────────────────────

@dataclass
class PlanStep:
    """计划中的单个步骤"""
    step: int
    description: str
    tool_name: str | None = None
    hint: str = ""

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "description": self.description,
            "tool_name": self.tool_name,
            "hint": self.hint,
        }


@dataclass
class Plan:
    """完整的执行计划"""
    steps: list[PlanStep]
    task_description: str = ""
    estimated_rounds: int = 0

    def to_dict(self) -> dict:
        return {
            "steps": [s.to_dict() for s in self.steps],
            "task_description": self.task_description,
            "estimated_rounds": self.estimated_rounds,
        }

    def to_hint_text(self) -> str:
        """格式化成自然语言提示文本，供 ReAct system_prompt 使用。"""
        if not self.steps:
            return ""
        lines = ["\n建议执行步骤（供参考，非强制顺序）:"]
        for s in self.steps:
            tool = f" → 工具: {s.tool_name}" if s.tool_name else " → 纯LLM推理"
            hint = f" ({s.hint})" if s.hint else ""
            lines.append(f"  {s.step}. {s.description}{tool}{hint}")
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# Schema & Prompt
# ──────────────────────────────────────────────────────────────────

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step": {"type": "integer"},
                    "description": {"type": "string", "description": "这步要做什么"},
                    "tool_name": {
                        "type": "string",
                        "nullable": True,
                        "description": "用哪个工具（纯推理步骤填null）",
                    },
                    "hint": {
                        "type": "string",
                        "description": "参数提示，如query关键词",
                    },
                },
                "required": ["step", "description"],
            },
        },
        "task_description": {"type": "string", "description": "整体任务描述"},
        "estimated_rounds": {"type": "integer"},
    },
    "required": ["steps", "task_description"],
}

_PLANNER_PROMPT = """你是一个任务规划器，负责把用户的结构化需求拆解为可执行步骤序列。

可用工具（按需选择）：
{tool_list}

拆解规则：
1. 每步只做一件事
2. 需要工具的步骤指定 tool_name，纯推理/生成步骤 tool_name 为 null
3. 步骤数控制在 2~5 步，不要过度拆解
4. hint 说明关键参数（如 query 关键词），不需要非常具体
5. 如果任务不需要拆解（单步即可完成），返回1步计划

用户问题：{user_message}
"""

# 工具列表（所有工具名，用于 prompt 中的格式化）
_TOOL_LIST_TEMPLATE = """
  - hybrid_search: 搜索用户记忆，输入关键词
  - fact_extractor: 从文本中提取结构化事实
  - time_resolver: 解析时间表达式（今天/昨天/上周等）
  - relation_finder: 查找记忆之间的关联
  - web_search: 搜索网络获取实时信息
  - weather: 查询指定城市的天气
"""


# ──────────────────────────────────────────────────────────────────
# Planner
# ──────────────────────────────────────────────────────────────────

class Planner:
    """
    任务规划器。

    用法:
        planner = Planner()
        plan = planner.create_plan("对比我记的两个健身方案", tool_registry)
        if plan:
            for step in plan.steps:
                print(step.description)
    """

    def __init__(self, llm_parse_json: Optional[Callable[..., Optional[dict]]] = None):
        self._llm_parse_json = llm_parse_json

    def create_plan(self, user_message: str, tool_registry: object) -> Optional[Plan]:
        """
        生成执行计划。失败返回 None，调用方降级为自由 ReAct。

        Args:
            user_message: 用户原始问题
            tool_registry: ToolRegistry 实例（用于验证 tool_name 是否存在）
        """
        text = (user_message or "").strip()
        if not text:
            return None

        parse_json = self._get_parse_json()
        if parse_json is None:
            return None

        prompt = _PLANNER_PROMPT.format(
            tool_list=_TOOL_LIST_TEMPLATE,
            user_message=text,
        )

        try:
            data = parse_json(prompt=prompt, schema=_PLAN_SCHEMA)
        except Exception:
            return None

        if not data or "steps" not in data:
            return None

        steps_raw = data["steps"]
        if not isinstance(steps_raw, list) or len(steps_raw) < 1 or len(steps_raw) > 5:
            return None

        steps: list[PlanStep] = []
        for s in steps_raw:
            step_num = s.get("step", len(steps) + 1)
            description = (s.get("description") or "").strip()
            if not description:
                continue
            tool_name = s.get("tool_name") or None
            hint = (s.get("hint") or "").strip()

            # 验证：如果指定了 tool_name，检查是否在 ToolRegistry 中
            if tool_name is not None:
                actual_tool = tool_registry.get_tool(tool_name) if hasattr(tool_registry, "get_tool") else None
                if actual_tool is None:
                    return None  # 工具不存在，验证失败

            steps.append(PlanStep(
                step=step_num,
                description=description,
                tool_name=tool_name,
                hint=hint,
            ))

        if len(steps) < 1:
            return None

        return Plan(
            steps=steps,
            task_description=data.get("task_description") or text,
            estimated_rounds=data.get("estimated_rounds", len(steps)),
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
