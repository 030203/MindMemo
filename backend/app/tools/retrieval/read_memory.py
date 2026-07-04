"""
ReadMemoryTool - 记忆全文读取工具

职责：按 memory_id 读取单条记忆的**完整正文**(content_raw)。

背景：
  hybrid_search 出于 token 预算只返回标题/摘要/标签 + 正文预览片段。
  当用户要求"总结简历""详细看某条记录"时，Agent 需要拿到完整正文，
  就先用 hybrid_search 定位 memory_id，再调本工具拉全文。

============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  memory_id: str   # 目标记忆 ID (通常来自 hybrid_search 结果)
  db / user_id     # 由 Agent 注入

[步骤2] 按 (memory_id, user_id) 查询，做归属校验
  memory_repository.get_for_user(db, user_id, memory_id)
  → 查不到 / 不属于该用户 → success=False

[步骤3] 返回 ToolResult
  data={
    "memory_id", "title", "category", "content",  # content = 完整 content_raw
    "tags", "keywords", "created_at", "source_type", "file_name"
  }

============================================================
测试要点:
  1. 正常读取: 返回完整 content_raw
  2. ID 不存在 / 非本人: success=False
  3. 非法 UUID: success=False，不抛异常
============================================================
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.timeutil import local_isoformat
from app.tools.base import BaseTool, ToolResult, ToolParameter, ToolParameterType

# 单条正文上限，避免超长文档(最大 30000 chars)一次性灌爆上下文
_MAX_CONTENT_CHARS = 16000


class ReadMemoryTool(BaseTool):
    """
    记忆全文读取工具 — 按 memory_id 拉取完整正文。

    与 hybrid_search 配合：先搜索定位，再读全文。
    """

    name: str = "read_memory"
    description: str = (
        "按 memory_id 读取单条记忆的完整正文(content_raw)。"
        "当需要记录的详细内容——例如总结/分析某篇文章、简历、笔记的全文——时，"
        "先用 hybrid_search 找到对应 memory_id，再用本工具获取完整文本。"
    )
    parameters: list[ToolParameter] = [
        ToolParameter(
            name="memory_id",
            type=ToolParameterType.STRING,
            description="要读取的记忆 ID，通常来自 hybrid_search 结果的 memory_id 字段",
            required=True,
        ),
    ]

    async def execute(self, **kwargs) -> ToolResult:
        # [步骤1] 接收参数
        memory_id_raw = kwargs.get("memory_id")
        db: Session | None = kwargs.get("db")
        user_id: uuid.UUID | None = kwargs.get("user_id")

        if not memory_id_raw:
            return ToolResult(success=False, error="memory_id 不能为空")
        if db is None or user_id is None:
            return ToolResult(
                success=False,
                error="缺少 db 或 user_id 上下文 —— Agent 调用时需注入",
            )

        # 容错解析 UUID（LLM 可能传入带引号/空格的字符串）
        try:
            memory_id = uuid.UUID(str(memory_id_raw).strip())
        except (ValueError, AttributeError):
            return ToolResult(success=False, error=f"非法的 memory_id: {memory_id_raw}")

        try:
            from app.repos.memory_repo import memory_repository

            memory = memory_repository.get_for_user(db, user_id, memory_id)
            if memory is None:
                return ToolResult(
                    success=False,
                    error="未找到该记忆，或它不属于当前用户。",
                )

            # [步骤3] 返回完整正文（截断保护）
            content = memory.content_raw or ""
            truncated = len(content) > _MAX_CONTENT_CHARS
            if truncated:
                content = content[:_MAX_CONTENT_CHARS]

            time_info = memory.time_info or {}
            return ToolResult(
                success=True,
                data={
                    "memory_id": str(memory.id),
                    "title": memory.title or "",
                    "category": memory.category,
                    "content": content,
                    "content_truncated": truncated,
                    "tags": memory.tags or [],
                    "keywords": memory.keywords or [],
                    "source_type": memory.source_type,
                    "file_name": time_info.get("file_name"),
                    # 记录时刻(本地时间)——解读正文里相对时间的锚点
                    "recorded_at": local_isoformat(memory.created_at),
                    "created_at": local_isoformat(memory.created_at),
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
