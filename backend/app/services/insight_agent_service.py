"""
InsightAgent - 后台分析 Agent（Phase 4）

职责：读取用户的记忆，分析出模式/趋势/洞察，写入 Insights 缓存。
  供后续 Fast 路径直接读取，无需现场分析。

触发：目前为 API 手动触发（POST /insights/generate）
      后续可扩展为定时任务/写入阈值自动触发。

============================================================
内部处理流程:
============================================================

[步骤1] 接收输入
  user_id: UUID
  db: Session
  days: int = 7       # 分析最近几天的记录
  force: bool = False  # 是否强制重新生成（覆盖已有）

[步骤2] 读取源数据
  从 memory_repository 加载:
    - 最近 days 天的记忆列表（含 category/tags/keywords/importance_score）
    - 按类别统计数量

[步骤3] 数据量判断
  if 记忆总数 < 1:
     不生成，返回 {skipped: True, reason: "数据不足"}
  if 记忆总数 < 3:
     跳过 LLM，只做简单统计（无 insight 写入，仅返回展示）

[步骤4] 主题聚类（纯规则，无 LLM）
  标签关键词频: dict[str, int]
  类别分布: dict[str, int]
  权重平均: importance_score 均值

[步骤5] LLM 生成自然语言洞察
  结构化数据 → 一次 parse_json 调用
  Schema: {insight_type, title, content: str, confidence}

[步骤6] 写入 Insights 缓存
  调 insight_repository.create(insight_type, title, content, data)
  expires_at = now + 7天（自动过期，保证洞察不会太久远）

[步骤7] 返回
  {success: True, insight_id, title, content_summary}

============================================================
测试要点:
  1. 有数据的: 插入 5 条记忆 → 生成洞察 → insights 表有记录
  2. 无数据: 记忆 0 条 → 跳过，不报错
  3. LLM 不可用: 记忆 ≥3 条但 LLM 挂 → 跳过 LLM 生成，返回统计数据
  4. 过期清理: create 时设 expires_at → 自动清理不干扰
============================================================
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.repos.memory_repo import memory_repository
from app.repos.insight_repo import insight_repository

logger = logging.getLogger(__name__)

# 拆分为"每周分析、学习总结、项目进展、生活模式"四种类型
_INSIGHT_TYPES = ("weekly", "learning", "project", "lifestyle")

# LLM 生成洞察的 schema
_INSIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "insight_type": {
            "type": "string",
            "enum": list(_INSIGHT_TYPES),
            "description": "最佳匹配的洞察类型",
        },
        "title": {"type": "string", "description": "洞察标题（一句话）"},
        "content": {
            "type": "string",
            "description": "洞察正文（150-300字，自然语言）",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "基于数据量的置信度",
        },
    },
    "required": ["insight_type", "title", "content", "confidence"],
}

_INSIGHT_PROMPT = """你是一个个人数据分析师。根据用户的记忆统计信息生成洞察。

用户的记忆统计：
{stats_json}

请基于这些数据生成一条有价值的洞察。要求：
1. 发现模式/规律（如最近专注什么领域、时间分布如何）
2. 不要泛泛而谈，要基于具体数字
3. 语气温和、有建设性
4. 篇幅 150-300 字
"""


class InsightAgent:
    """
    洞察生成 Agent — 读取用户记忆 → 分析 → 写入 insights 表。
    """

    def __init__(self, llm_parse_json: Optional[Callable[..., Optional[dict]]] = None):
        self._llm_parse_json = llm_parse_json

    async def generate_insight(
        self,
        db: Session,
        user_id: UUID,
        days: int = 7,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        为指定用户生成最近 days 天的洞察。

        Returns:
            {success, insight_id?, title?, content_summary?, skipped?, reason?}
        """
        # ── [步骤2] 读取源数据 ────────────────────────────────────
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        try:
            memories = memory_repository.list_for_user(db, user_id) or []
            memories = [
                m for m in memories
                if not hasattr(m, "created_at") or not m.created_at
                or (m.created_at.replace(tzinfo=timezone.utc) if m.created_at.tzinfo is None else m.created_at) >= cutoff
            ]
        except Exception as e:
            logger.warning("InsightAgent: 读取记忆失败 %s", e)
            return {"success": False, "error": "读取记忆失败"}

        # ── [步骤3] 数据量判断 ──────────────────────────────────
        if len(memories) < 1:
            return {"success": True, "skipped": True, "reason": "数据不足，最近{0}天无记忆".format(days)}

        # ── [步骤4] 结构化统计（纯规则）──────────────────────────
        stats = self._compute_stats(memories)

        if len(memories) < 3:
            # 数据太少，不适合 LLM 生成
            return {
                "success": True,
                "skipped": True,
                "reason": f"数据仅 {len(memories)} 条，跳过 LLM 生成",
                "stats": stats,
            }

        # ── [步骤5] LLM 生成自然语言洞察 ───────────────────────
        parse_json = self._get_parse_json()
        if parse_json is None:
            # LLM 不可用，返回统计数据
            return {
                "success": True,
                "skipped": True,
                "reason": "LLM 不可用",
                "stats": stats,
            }

        prompt = _INSIGHT_PROMPT.format(
            stats_json=json.dumps(stats, ensure_ascii=False, indent=2)
        )

        try:
            result = parse_json(prompt=prompt, schema=_INSIGHT_SCHEMA)
        except Exception as e:
            logger.warning("InsightAgent: LLM 生成失败 %s", e)
            return {"success": True, "skipped": True, "reason": "LLM 生成失败", "stats": stats}

        if result is None:
            return {"success": True, "skipped": True, "reason": "LLM 返回无效", "stats": stats}

        confidence = result.get("confidence", 0.5)
        insight_type = result.get("insight_type", "weekly")
        title = (result.get("title") or "").strip()
        content = (result.get("content") or "").strip()
        if not title or not content:
            return {"success": True, "skipped": True, "reason": "LLM 结果为空", "stats": stats}

        # ── [步骤6] 写入 Insights 缓存 ──────────────────────────
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)

        try:
            insight = insight_repository.create(
                db=db,
                user_id=user_id,
                insight_type=insight_type,
                title=title,
                content=content,
                data={"stats": stats, "memory_count": len(memories), "days": days},
                confidence_score=confidence,
                expires_at=expires_at,
            )
        except Exception as e:
            logger.warning("InsightAgent: 写入洞察失败 %s", e)
            return {"success": False, "error": f"写入洞察失败: {e}"}

        # ── [步骤7] 返回 ─────────────────────────────────────────
        return {
            "success": True,
            "insight_id": str(insight.id),
            "title": insight.title,
            "content_summary": insight.content[:100] + "..." if len(insight.content) > 100 else insight.content,
            "insight_type": insight_type,
            "confidence": confidence,
            "memory_count": len(memories),
        }

    @staticmethod
    def _compute_stats(memories: list) -> dict:
        """从记忆列表中计算结构化统计信息。"""
        cat_counter: Counter = Counter()
        tag_counter: Counter = Counter()
        total_importance = 0.0

        for m in memories:
            if m.category:
                cat_counter[m.category] += 1
            tags = m.tags or []
            for t in tags:
                tag_counter[t] += 1
            total_importance += getattr(m, "importance_score", 0.0) or 0.0

        return {
            "total_count": len(memories),
            "category_distribution": dict(cat_counter.most_common()),
            "top_tags": [t for t, _ in tag_counter.most_common(10)],
            "average_importance": round(total_importance / max(len(memories), 1), 2),
        }

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


insight_agent = InsightAgent()
