"""
FactExtractorTool - 事实提取工具

职责：调用 LLM 从文本中提取结构化事实三元组 (subject, predicate, object)

============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  text: str              # 待提取的文本
  max_facts: int = 10    # 最多提取几条事实

[步骤2] 文本预处理
  - 截断过长文本 (max 4000 chars) → 防止 LLM 上下文窗口溢出
  - 去首尾空白

[步骤3] LLM 结构化提取
  调 LLMClient.parse_json(
    prompt=f"提取文本中的事实:\n\n{text}",
    schema={
      "facts": [
        {"subject": "str", "predicate": "str", "object": "str", "confidence": 0.0-1.0}
      ]
    }
  )

[步骤4] 去重 + 排序
  - 将 (subject,predicate,object) 三元组做 key，相同 key 只保留 confidence 最高的
  - 按 confidence 降序
  - 截断 max_facts

[步骤5] 返回 ToolResult
  ToolResult(
    success=True,
    data={
      "facts": [
        {"subject": "用户", "predicate": "学习了", "object": "Python闭包", "confidence": 0.95}
      ],
      "total_extracted": 1,
      "source_text_length": 50
    }
  )

============================================================
测试要点:
  1. 简单句: "我昨天学了Python" → 1条事实
  2. 多事实: 一段话含3个知识点 → 3条事实
  3. 空文本: "" → 空列表, success=True
============================================================
"""
from __future__ import annotations

from app.tools.base import BaseTool, ToolResult, ToolParameter, ToolParameterType

# LLM 结构化输出的 JSON Schema
_FACT_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "事实的主体，如'用户'、'Python'、'某项目'",
                    },
                    "predicate": {
                        "type": "string",
                        "description": "关系或动作，如'学习了'、'位于'、'创建了'",
                    },
                    "object": {
                        "type": "string",
                        "description": "事实的客体，如'闭包'、'北京'、'todo'",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "提取置信度",
                    },
                },
                "required": ["subject", "predicate", "object", "confidence"],
            },
        }
    },
    "required": ["facts"],
}

_MAX_CHARS = 4000


def _make_fact_key(f: dict) -> tuple:
    """构建去重 key：(subject_lower, predicate_lower, object_lower)"""
    return (
        f.get("subject", "").strip().lower(),
        f.get("predicate", "").strip().lower(),
        f.get("object", "").strip().lower(),
    )


class FactExtractorTool(BaseTool):
    """
    事实提取器 — 从文本中抽结构化 (S,P,O) 三元组

    用于 Agent 对检索到的记忆做二次结构化，便于后续分析、对比、汇总。
    """

    name: str = "fact_extractor"
    description: str = (
        "从文本中提取结构化事实三元组。"
        "每条事实包含 subject(主体)、predicate(谓词/关系)、object(客体) 和 confidence。"
        "适用于对用户记忆内容做结构化分析。"
    )
    parameters: list[ToolParameter] = [
        ToolParameter(
            name="text",
            type=ToolParameterType.STRING,
            description="待提取的原始文本",
            required=True,
        ),
        ToolParameter(
            name="max_facts",
            type=ToolParameterType.INTEGER,
            description="最多提取的事实条数，默认 10",
            required=False,
            default=10,
        ),
    ]

    async def execute(self, **kwargs) -> ToolResult:
        # [步骤1] 接收参数
        text: str = kwargs.get("text", "")
        max_facts: int = kwargs.get("max_facts", 10)

        # [步骤2] 文本预处理
        text = text.strip()
        if not text:
            return ToolResult(
                success=True,
                data={"facts": [], "total_extracted": 0, "source_text_length": 0},
            )
        if len(text) > _MAX_CHARS:
            text = text[:_MAX_CHARS]

        # [步骤3] LLM 结构化提取
        llm_client = kwargs.get("llm_client")
        if llm_client is None:
            return ToolResult(
                success=False,
                error="缺少 llm_client，Agent 调用时需通过 kwargs 注入",
            )

        try:
            parsed = await llm_client.parse_json(
                prompt=f"提取以下文本中的结构化事实:\n\n{text}",
                schema=_FACT_SCHEMA,
            )
        except Exception as exc:
            return ToolResult(success=False, error=f"LLM 调用失败: {exc}")

        if parsed is None or "facts" not in parsed:
            return ToolResult(
                success=True,
                data={"facts": [], "total_extracted": 0, "source_text_length": len(text)},
            )

        raw_facts: list[dict] = parsed["facts"]

        # [步骤4] 去重 + 排序 + 截断
        seen: dict[tuple, dict] = {}
        for f in raw_facts:
            key = _make_fact_key(f)
            if key not in seen or f.get("confidence", 0) > seen[key].get("confidence", 0):
                seen[key] = f

        deduped = sorted(
            seen.values(), key=lambda f: f.get("confidence", 0), reverse=True
        )[:max_facts]

        # [步骤5] 返回
        return ToolResult(
            success=True,
            data={
                "facts": deduped,
                "total_extracted": len(deduped),
                "source_text_length": len(text),
            },
        )
