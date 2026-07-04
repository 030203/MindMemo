"""
MemoryWriteTool - Agent 自主写记忆

职责：让 Agent 在对话中帮用户创建/更新记忆，带自动分类和低置信度保护。

============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  title: str           # 标题
  content: str         # 正文
  category: str = None # 类别 (笔记/想法/待办/...)
  tags: list[str] = [] # 标签

[步骤2] 内容清洗
  去首尾空白，去连续空白行

[步骤3] AI 增强 (需要 LLMClient 注入)
  [3.1] category 为空 → 调 LLM 自动分类
  [3.2] tags 为空 → 调 LLM 自动提取标签/关键词
  [3.3] 生成 content_summary (不超过 200 字)

[步骤4] 写入数据库
  调用 memory_repository.create()
  标记 created_by="agent"

[步骤5] 触发 ReviewQueue (低置信度保护)
  如果 AI 自动分类置信度 < 0.7:
    创建 ReviewQueue 条目
  如果 category 为空且 LLM 不可用:
    category fallback = "memo"，needs_review=True

[步骤6] 写 Timeline
  创建 timeline_event

[步骤7] 返回 ToolResult

============================================================
测试要点:
  1. 完整写入: title+content+category+tags → 成功入库
  2. 自动分类: category 为空 → AI 分类 → 入库
  3. ReviewQueue触发: 低置信度 → needs_review=True
  4. 空标题: title="" → success=False
  5. 超长内容: 3000字 → 自动截断 + 摘要
============================================================
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.tools.base import BaseTool, ToolResult, ToolParameter, ToolParameterType

_MAX_TITLE = 255
_MAX_CONTENT = 8000
_MAX_SUMMARY = 200

# LLM 自动分类的 JSON Schema
_CATEGORY_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": ["学习笔记", "项目", "想法", "备忘", "生活", "其他"],
            "description": "最佳匹配类别",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2~5个标签",
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2~5个关键词",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "分类置信度",
        },
    },
    "required": ["category", "tags", "keywords", "confidence"],
}


def _summarize(content: str, max_len: int = _MAX_SUMMARY) -> str:
    """生成简单摘要：去换行 + 截断"""
    compact = content.strip().replace("\n", " ").replace("\r", " ")
    if len(compact) <= max_len:
        return compact
    return f"{compact[:max_len-3].rstrip()}..."


class MemoryWriteTool(BaseTool):
    """
    Agent 记忆写入器 — 帮用户在对话中创建记忆

    安全设计: 低置信度的自动分类 → 标记需要审查 (ReviewQueue)
    (对齐规范: "不允许做成黑盒自动修改核心用户数据")
    """

    name: str = "memory_write"
    description: str = (
        "帮用户创建一条新记忆，或更新已有记忆。"
        "自动补充缺失的 category、tags、keywords，"
        "低置信度的自动分类会标记为待用户确认。"
    )
    parameters: list[ToolParameter] = [
        ToolParameter(
            name="title",
            type=ToolParameterType.STRING,
            description="记忆标题，必填",
            required=True,
        ),
        ToolParameter(
            name="content",
            type=ToolParameterType.STRING,
            description="记忆正文",
            required=True,
        ),
        ToolParameter(
            name="category",
            type=ToolParameterType.STRING,
            description="记忆类别，如'学习笔记'、'项目'、'备忘'。不传则由 AI 自动分类",
            required=False,
        ),
        ToolParameter(
            name="tags",
            type=ToolParameterType.ARRAY,
            description="标签列表，如['Python','编程']。不传则自动提取",
            required=False,
        ),
        ToolParameter(
            name="memory_id",
            type=ToolParameterType.STRING,
            description="要更新的记忆 UUID。不传则创建新记忆",
            required=False,
        ),
    ]

    async def execute(self, **kwargs) -> ToolResult:
        # [步骤1] 接收参数
        title: str = (kwargs.get("title") or "").strip()
        content: str = (kwargs.get("content") or "").strip()
        category: str | None = (kwargs.get("category") or "").strip() or None
        tags: list[str] | None = kwargs.get("tags")
        memory_id_str: str | None = kwargs.get("memory_id")

        db: Session | None = kwargs.get("db")
        user_id: uuid.UUID | None = kwargs.get("user_id")
        llm_client = kwargs.get("llm_client")

        if db is None or user_id is None:
            return ToolResult(
                success=False,
                error="缺少 db 或 user_id 上下文 —— Agent 调用时需注入",
            )

        # [步骤2] 校验 + 清洗
        if not title:
            return ToolResult(success=False, error="title 不能为空")
        if not content:
            return ToolResult(success=False, error="content 不能为空")

        title = title[:_MAX_TITLE]
        content = content[:_MAX_CONTENT]

        # [步骤3] AI 增强
        needs_review = False
        ai_tags: list[str] = []
        ai_keywords: list[str] = []
        confidence = 1.0

        if category is None or (tags is None or len(tags) == 0):
            # 需要 LLM 辅助
            if llm_client is None:
                # 无 LLM → fallback
                category = category or "备忘"
                tags = list(tags) if tags else ["记录"]
                needs_review = True
            else:
                try:
                    ai_result = await llm_client.parse_json(
                        prompt=f"标题: {title}\n\n正文: {content[:2000]}",
                        schema=_CATEGORY_SCHEMA,
                    )
                except Exception:
                    ai_result = None

                if ai_result is None:
                    category = category or "备忘"
                    tags = list(tags) if tags else ["记录"]
                    needs_review = True
                else:
                    if category is None:
                        category = ai_result.get("category", "备忘")
                    ai_tags = ai_result.get("tags", [])
                    ai_keywords = ai_result.get("keywords", [])
                    confidence = ai_result.get("confidence", 0.5)
                    # [步骤5] 低置信度 → ReviewQueue
                    if confidence < 0.7:
                        needs_review = True

        # 合并 tags：用户提供的 + AI 提取的，去重
        final_tags = list(dict.fromkeys(
            (list(tags) if tags else []) + ai_tags
        )) or ["记录"]

        # 摘要
        summary = _summarize(content)

        # [步骤4] 写入数据库
        from app.models.memory import MemoryItem
        from app.repos.memory_repo import memory_repository

        try:
            if memory_id_str:
                # 更新已有记忆
                try:
                    mem_id = uuid.UUID(memory_id_str)
                except ValueError:
                    return ToolResult(success=False, error=f"无效 UUID: {memory_id_str}")
                existing = memory_repository.get_for_user(db, user_id, mem_id)
                if existing is None:
                    return ToolResult(success=False, error=f"记忆 {memory_id_str} 不存在")
                existing.title = title
                existing.content_raw = content
                existing.content_clean = content
                existing.content_summary = summary
                existing.category = category
                existing.tags = final_tags
                existing.keywords = ai_keywords
                existing.created_by = "agent"
                db.flush()
                result_id = str(existing.id)
            else:
                # 创建新记忆
                now = datetime.now(timezone.utc)
                memory = MemoryItem(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    source_type="agent",
                    title=title,
                    content_raw=content,
                    content_clean=content,
                    content_summary=summary,
                    category=category,
                    tags=final_tags,
                    keywords=ai_keywords,
                    entities=[],
                    time_info={},
                    importance_score=0.5,
                    status="active",
                    created_by="agent",
                    event_time=now,
                )
                memory_repository.create(db, memory)
                result_id = str(memory.id)

            # [步骤6] 写 Timeline
            from app.models.timeline import TimelineEvent
            from app.repos.timeline_repo import timeline_repository

            timeline = TimelineEvent(
                id=uuid.uuid4(),
                user_id=user_id,
                event_type=f"memory_{'update' if memory_id_str else 'create'}",
                ref_type="memory",
                ref_id=uuid.UUID(result_id),
                title=f"{'更新' if memory_id_str else '创建'}了记忆: {title}",
                summary=summary,
                event_time=datetime.now(timezone.utc),
            )
            timeline_repository.create(db, timeline)

            # [步骤5] 触发 ReviewQueue（低置信度保护）
            review_id = None
            if needs_review:
                from app.models.review import ReviewQueueItem

                review_item = ReviewQueueItem(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    review_type="ai_classification",
                    target_type="memory",
                    target_id=uuid.UUID(result_id),
                    suggestion={
                        "category": category,
                        "tags": final_tags,
                        "keywords": ai_keywords,
                        "confidence": confidence,
                        "message": "AI 自动分类置信度较低，请确认记忆的分类和标签是否正确",
                    },
                    user_decision=None,
                    status="pending",
                    reason="AI 自动分类置信度 < 0.7",
                )
                db.add(review_item)
                db.flush()
                review_id = str(review_item.id)

            # [步骤7] 返回
            return ToolResult(
                success=True,
                data={
                    "memory_id": result_id,
                    "title": title,
                    "category": category,
                    "tags": final_tags,
                    "summary": summary,
                    "needs_review": needs_review,
                    "review_id": review_id,
                    "action": "update" if memory_id_str else "create",
                },
            )

        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
