"""
RelationFinderTool - 记忆关系发现工具

职责：给定一条记忆 ID，扫描用户记忆库，找出关联最强的记忆

============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  memory_id: str             # 源记忆 ID
  max_relations: int = 10

[步骤2] 获取源记忆
  调用 memory_repository.get_for_user(memory_id) 获取详情
  提取 tags / keywords / entities / category / event_time

[步骤3] 多维相似度匹配 (纯规则引擎，不调 LLM)
  [3.1] 标签重叠: 共享 tags 越多 → 分数越高
  [3.2] 关键词重叠: Jaccard 相似度
  [3.3] 实体重叠: 共享 entities (人名/地名/技术名)
  [3.4] 时间接近: event_time 在 24h 内 → 加分
  [3.5] 同类别: 相同 category → 加分

[步骤4] 合并排序
  - 加权合并所有维度分数
  - 去重 (排除自身)
  - 按综合分数降序，取 top max_relations

[步骤5] 返回 ToolResult

============================================================
测试要点:
  1. 有关联: 两条都有 "Python" 标签 → 返回关系
  2. 无关联: 完全不相关的记忆 → 空列表
  3. 排除自身: 不会把自己列为关联
============================================================
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.tools.base import BaseTool, ToolResult, ToolParameter, ToolParameterType


def _field_overlap(a: list, b: list) -> int:
    """计算两个列表的元素重叠数 (大小写不敏感)"""
    if not a or not b:
        return 0
    set_a = {x.lower() if isinstance(x, str) else str(x).lower() for x in a}
    set_b = {x.lower() if isinstance(x, str) else str(x).lower() for x in b}
    return len(set_a & set_b)


def _jaccard(a: list, b: list) -> float:
    """Jaccard 相似度"""
    if not a and not b:
        return 0.0
    set_a = {x.lower() if isinstance(x, str) else str(x).lower() for x in a}
    set_b = {x.lower() if isinstance(x, str) else str(x).lower() for x in b}
    union = len(set_a | set_b)
    if union == 0:
        return 0.0
    return len(set_a & set_b) / union


def _category_bonus(src_cat: str, tgt_cat: str) -> float:
    """同类别加分"""
    return 0.15 if src_cat == tgt_cat else 0.0


def _time_bonus(src_time, tgt_time) -> float:
    """时间接近加分"""
    if src_time is None or tgt_time is None:
        return 0.0
    # 确保 aware
    def ensure_tz(dt):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    delta = abs((ensure_tz(src_time) - ensure_tz(tgt_time)).total_seconds())
    if delta <= 3600:       # 1 小时内 → 0.20
        return 0.20
    if delta <= 86400:      # 24 小时内 → 0.10
        return 0.10
    if delta <= 604800:     # 1 周内     → 0.05
        return 0.05
    return 0.0


class RelationFinderTool(BaseTool):
    """
    记忆关系发现器 — 给定一条记忆，找出最相关的其他记忆

    纯规则引擎，不调 LLM（确定性高、零延迟、适合批量跑）。
    适用于 Agent 在展示某条记忆时扩展显示关联内容，或 Memory Manager 异步关联发现。
    """

    name: str = "relation_finder"
    description: str = (
        "查找与指定记忆最相关的其他记忆。"
        "基于标签、关键词、实体、类别、时间等多维相似度计算。"
        "输入 memory_id，返回按相关性排序的关联记忆列表。"
    )
    parameters: list[ToolParameter] = [
        ToolParameter(
            name="memory_id",
            type=ToolParameterType.STRING,
            description="源记忆的 UUID",
            required=True,
        ),
        ToolParameter(
            name="max_relations",
            type=ToolParameterType.INTEGER,
            description="最多返回几条关联，默认 10",
            required=False,
            default=10,
        ),
    ]

    async def execute(self, **kwargs) -> ToolResult:
        # [步骤1] 接收参数
        memory_id_str: str = kwargs.get("memory_id", "")
        max_relations: int = kwargs.get("max_relations", 10)

        if not memory_id_str.strip():
            return ToolResult(success=False, error="memory_id 不能为空")

        db: Session | None = kwargs.get("db")
        user_id: uuid.UUID | None = kwargs.get("user_id")
        if db is None or user_id is None:
            return ToolResult(
                success=False,
                error="缺少 db 或 user_id 上下文 —— Agent 调用时需注入",
            )

        try:
            memory_id = uuid.UUID(memory_id_str)
        except ValueError:
            return ToolResult(success=False, error=f"无效的 UUID: {memory_id_str}")

        try:
            # [步骤2] 获取源记忆
            from app.repos.memory_repo import memory_repository

            source = memory_repository.get_for_user(db, user_id, memory_id)
            if source is None:
                return ToolResult(success=False, error=f"记忆 {memory_id_str} 不存在")

            # [步骤3] 多维相似度匹配
            all_memories = memory_repository.list_for_user(db, user_id)

            scored = []
            for m in all_memories:
                if m.id == memory_id:  # 排除自身
                    continue

                score = 0.0
                fields_contrib: list[str] = []

                # [3.1] 标签重叠 (权重 0.25)
                tag_overlap = _field_overlap(source.tags, m.tags)
                if tag_overlap > 0:
                    s = min(tag_overlap * 0.08, 0.25)
                    score += s
                    fields_contrib.append(f"tags({tag_overlap})")

                # [3.2] 关键词重叠 —— Jaccard (权重 0.20)
                kw_jaccard = _jaccard(source.keywords, m.keywords)
                if kw_jaccard > 0:
                    s = kw_jaccard * 0.20
                    score += s
                    fields_contrib.append(f"keywords")

                # [3.3] 实体重叠 (权重 0.15)
                ent_overlap = _field_overlap(source.entities, m.entities)
                if ent_overlap > 0:
                    s = min(ent_overlap * 0.05, 0.15)
                    score += s
                    fields_contrib.append(f"entities({ent_overlap})")

                # [3.4] 时间接近 (权重 0.20)
                tb = _time_bonus(
                    source.event_time or source.created_at,
                    m.event_time or m.created_at,
                )
                if tb > 0:
                    score += tb
                    fields_contrib.append("time")

                # [3.5] 同类别 (权重 0.15)
                cb = _category_bonus(source.category, m.category)
                if cb > 0:
                    score += cb
                    fields_contrib.append("category")

                if score > 0:
                    scored.append({
                        "target_memory_id": str(m.id),
                        "title": m.title or "",
                        "score": round(score, 4),
                        "overlap_fields": fields_contrib,
                    })

            # [步骤4] 合并排序 + 截断
            ranked = sorted(scored, key=lambda x: x["score"], reverse=True)[
                :max_relations
            ]

            # [步骤5] 返回
            return ToolResult(
                success=True,
                data={
                    "source_memory_id": str(memory_id),
                    "source_title": source.title or "",
                    "relations": ranked,
                },
            )

        except Exception as exc:
            return ToolResult(success=False, error=str(exc))
