"""
MemoryManager (maintenance) - 后台异步维护

职责：定期打扫记忆库，保证质量。
  - 去重: 发现高度相似的记忆 → ReviewQueue
  - 衰减: 长期未访问的记忆 → 降低 importance_score
  - 过期清理: 清理已过期的 Insights

============================================================
内部处理流程:
============================================================

[步骤1] 触发（外部调用 run_maintenance）

[步骤2] 去重检查
  扫描最近 30 天的记忆:
    标题 Jaccard 相似度 > 0.85 → 标记为疑似重复
    创建 ReviewQueue 条目，不自动合并

[步骤3] 权重衰减
  last_recalled_at > 90天  → importance_score *= 0.5
  last_recalled_at > 180天 → importance_score *= 0.3

[步骤4] 清理过期 Insights  → insight_repository.delete_expired()

[步骤5] 返回 MaintenanceReport
============================================================
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.repos.memory_repo import memory_repository
from app.repos.review_repo import review_repository
from app.repos.insight_repo import insight_repository
from app.models.review import ReviewQueueItem
from app.models.memory import MemoryItem
from app.models.user import User

logger = logging.getLogger(__name__)

# ── 阈值常量 ─────────────────────────────────────────────────────
_DEDUP_WINDOW_DAYS = 30       # 去重扫描范围
_DEDUP_SIMILARITY_THRESHOLD = 0.7
_DECAY_90_DAYS = 0.5
_DECAY_180_DAYS = 0.3


def run_maintenance(db: Session, user_id: uuid.UUID | None = None) -> dict[str, Any]:
    """
    执行一次记忆库维护。

    Args:
        db: 数据库会话
        user_id: 可选，仅对指定用户执行；None 则全量执行

    Returns:
        MaintenanceReport dict
    """
    report: dict[str, Any] = {
        "duplicates_found": 0,
        "duplicate_pairs": [],
        "decayed_memories": 0,
        "expired_insights": 0,
        "users_processed": 0,
    }

    # 获取用户列表
    if user_id is not None:
        user_ids = [user_id]
    else:
        user_ids = _get_all_user_ids(db)

    report["users_processed"] = len(user_ids)
    now = datetime.now(timezone.utc)

    for uid in user_ids:
        try:
            # 去重
            dup_count, dup_pairs = _dedup(db, uid)
            report["duplicates_found"] += dup_count
            report["duplicate_pairs"].extend(dup_pairs)

            # 衰减
            decayed = _decay(db, uid)
            report["decayed_memories"] += decayed

            # 更新时间戳
            db.query(User).filter(User.id == uid).update({"last_maintenance_at": now})

        except Exception:
            logger.warning("maintenance user %s failed", uid, exc_info=True)

    # 过期 Insights 清理（全局）
    try:
        report["expired_insights"] = insight_repository.delete_expired(db)
    except Exception:
        logger.warning("expired insights cleanup failed", exc_info=True)

    # 清理 duplicate_pairs（大列表不返回细节，只返回计数）
    del report["duplicate_pairs"]

    return report


def _get_all_user_ids(db: Session) -> list[uuid.UUID]:
    """获取所有用户的 ID 列表。"""
    from sqlalchemy import text
    rows = db.execute(text("SELECT DISTINCT user_id FROM memory_items WHERE status = 'active'")).fetchall()
    return [row[0] for row in rows]


def _dedup(db: Session, user_id: uuid.UUID) -> tuple[int, list[dict]]:
    """对单个用户执行去重检查。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=_DEDUP_WINDOW_DAYS)
    memories = (
        db.query(MemoryItem)
        .filter(
            MemoryItem.user_id == user_id,
            MemoryItem.status == "active",
        )
        .all()
    )

    # 过滤时间
    recent = [
        m for m in memories
        if m.created_at and (
            m.created_at.replace(tzinfo=timezone.utc) if m.created_at.tzinfo is None else m.created_at
        ) >= cutoff
    ]

    pairs: list[dict] = []
    checked: set[tuple[uuid.UUID, uuid.UUID]] = set()

    for i in range(len(recent)):
        for j in range(i + 1, len(recent)):
            a, b = recent[i], recent[j]
            key = (a.id, b.id) if a.id < b.id else (b.id, a.id)
            if key in checked:
                continue
            checked.add(key)

            similarity = _jaccard_similarity((a.title or ""), (b.title or ""))
            if similarity >= _DEDUP_SIMILARITY_THRESHOLD:
                _create_dedup_review(db, user_id, a, b, similarity)
                pairs.append({
                    "memory_id_a": str(a.id),
                    "memory_id_b": str(b.id),
                    "title_a": a.title,
                    "title_b": b.title,
                    "similarity": round(similarity, 2),
                })

    return len(pairs), pairs


def _jaccard_similarity(a: str, b: str) -> float:
    """两个字符串的 Jaccard 相似度（基于字符集合）。"""
    if not a or not b:
        return 0.0
    set_a, set_b = set(a), set(b)
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union) if union else 0.0


def _create_dedup_review(
    db: Session, user_id: uuid.UUID,
    a: MemoryItem, b: MemoryItem,
    similarity: float,
):
    """创建去重 ReviewQueue 条目（不自动合并）。"""
    existing = review_repository.get_pending_for_target(
        db, user_id, review_type="duplicate_detection", target_type="memory", target_id=a.id
    )
    if existing is not None:
        return

    review_item = ReviewQueueItem(
        id=uuid.uuid4(),
        user_id=user_id,
        review_type="duplicate_detection",
        target_type="memory",
        target_id=a.id,
        suggestion={
            "type": "duplicate",
            "similarity": round(similarity, 2),
            "duplicate_of_id": str(b.id),
            "duplicate_title": b.title or "",
            "message": (
                f"记忆「{a.title}」与「{b.title}」"
                f"相似度 {similarity:.0%}，可能重复。请确认是否合并。"
            ),
        },
        status="pending",
        reason=f"自动检测到标题相似度过高 ({similarity:.0%})",
    )
    review_repository.create(db, review_item)


def _decay(db: Session, user_id: uuid.UUID) -> int:
    """对单个用户执行权重衰减。"""
    now = datetime.now(timezone.utc)
    count = 0

    memories = (
        db.query(MemoryItem)
        .filter(
            MemoryItem.user_id == user_id,
            MemoryItem.status == "active",
        )
        .all()
    )

    for m in memories:
        last_access = m.last_recalled_at
        if last_access is None:
            continue
        if last_access.tzinfo is None:
            last_access = last_access.replace(tzinfo=timezone.utc)

        days_since = (now - last_access).days
        if days_since > 180:
            m.importance_score = round(m.importance_score * _DECAY_180_DAYS, 2)
            count += 1
        elif days_since > 90:
            m.importance_score = round(m.importance_score * _DECAY_90_DAYS, 2)
            count += 1

    db.commit()
    return count


def cleanup_expired_insights(db: Session) -> int:
    """清理过期的 Insight 记录。"""
    return insight_repository.delete_expired(db)
