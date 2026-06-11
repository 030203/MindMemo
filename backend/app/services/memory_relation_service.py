from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from math import exp

from sqlalchemy.orm import Session

from app.models.memory import ExtractedFact, MemoryItem, MemoryRelation
from app.repos.fact_repo import fact_repository
from app.repos.memory_relation_repo import memory_relation_repository
from app.repos.memory_repo import memory_repository
from app.schemas.memory import MemoryRelatedItem


@dataclass(frozen=True)
class RelationCandidate:
    memory: MemoryItem
    relation_type: str
    reason: str
    score: float


def _string_set(values: list | None) -> set[str]:
    return {str(value).strip().lower() for value in (values or []) if str(value).strip()}


RELATION_STOP_TERMS = {
    "memo",
    "record",
    "learning",
    "knowledge",
    "project",
    "progress",
    "idea",
    "inspiration",
}


def _payload_terms(fact: ExtractedFact) -> set[str]:
    payload = dict(fact.structured_payload or {})
    terms: set[str] = set()
    if fact.fact_type == "learning":
        terms.update(f"topic:{item.strip().lower()}" for item in payload.get("topics", []) if str(item).strip())
    elif fact.fact_type == "expense":
        category = str(payload.get("category") or "").strip().lower()
        if category and category != "other":
            terms.add(f"expense_category:{category}")
    elif fact.fact_type == "mood":
        label = str(payload.get("label") or "").strip().lower()
        kind = str(payload.get("kind") or "").strip().lower()
        if label:
            terms.add(f"mood_label:{label}")
        if kind:
            terms.add(f"mood_kind:{kind}")
    elif fact.fact_type == "plan":
        due_time = str(payload.get("due_time") or "").strip()
        if due_time:
            terms.add(f"plan_due:{due_time[:10]}")
    return terms


def _fact_terms(facts: list[ExtractedFact]) -> set[str]:
    terms: set[str] = set()
    for fact in facts:
        terms.update(_payload_terms(fact))
    return terms


def _temporal_score(left: datetime | None, right: datetime | None) -> float:
    if not left or not right:
        return 0.0
    days = abs((left - right).total_seconds()) / 86400
    if days > 45:
        return 0.0
    return 0.16 * exp(-days / 14)


def _memory_terms(memory: MemoryItem) -> set[str]:
    terms = _string_set(memory.tags) | _string_set(memory.keywords) | _string_set(memory.entities)
    if memory.category:
        terms.add(memory.category.lower())
    return terms - RELATION_STOP_TERMS


def _has_negative_relation_marker(memory: MemoryItem) -> bool:
    text = f"{memory.title or ''} {memory.content_summary or ''} {memory.content_clean or ''} {memory.content_raw or ''}".lower()
    return any(marker in text for marker in ["\u65e0\u5173", "\u4e0d\u662f", "not related", "unrelated"])


def _best_relation_type(
    *,
    shared_terms: set[str],
    shared_fact_terms: set[str],
    shared_entities: set[str],
    same_category: bool,
    temporal_score: float,
) -> tuple[str, str]:
    if shared_fact_terms:
        sample = ", ".join(sorted(shared_fact_terms)[:3])
        return "shared_fact", f"Shared structured fact signals: {sample}"
    if shared_entities:
        sample = ", ".join(sorted(shared_entities)[:3])
        return "shared_entity", f"Shared entities or topics: {sample}"
    if shared_terms:
        sample = ", ".join(sorted(shared_terms)[:3])
        return "shared_semantic_signal", f"Shared semantic signals: {sample}"
    if same_category:
        return "same_category", "Same memory category"
    if temporal_score > 0:
        return "temporal_neighbor", "Events are close on the timeline"
    return "weak_context", "Weak contextual similarity"


def _to_related_item(relation: MemoryRelation, memory: MemoryItem) -> MemoryRelatedItem:
    return MemoryRelatedItem(
        id=str(memory.id),
        title=memory.title or "Untitled Memory",
        content_summary=memory.content_summary or "",
        category=memory.category,
        relation_type=relation.relation_type,
        relation_reason=relation.relation_reason or "",
        score=float(relation.score),
        event_time=memory.event_time,
    )


class MemoryRelationService:
    def list_related(
        self,
        db: Session,
        user_id: uuid.UUID,
        memory_id: str,
        *,
        limit: int = 8,
    ) -> list[MemoryRelatedItem]:
        target_id = uuid.UUID(memory_id)
        relations = memory_relation_repository.list_from_memory(db, user_id, target_id, limit=limit)
        related: list[MemoryRelatedItem] = []
        for relation in relations:
            memory = memory_repository.get_for_user(db, user_id, relation.to_memory_id)
            if memory is not None:
                related.append(_to_related_item(relation, memory))
        return related

    def rebuild_for_memory(
        self,
        db: Session,
        user_id: uuid.UUID,
        memory: MemoryItem,
        *,
        limit: int = 8,
    ) -> list[MemoryRelation]:
        facts_by_memory = self._facts_by_memory(db, user_id)
        candidates = self._rank_candidates(memory, memory_repository.list_for_user(db, user_id), facts_by_memory)
        selected = candidates[:limit]

        memory_relation_repository.delete_for_memory(db, user_id, memory.id)
        relations: list[MemoryRelation] = []
        for candidate in selected:
            relations.append(
                MemoryRelation(
                    user_id=user_id,
                    from_memory_id=memory.id,
                    to_memory_id=candidate.memory.id,
                    relation_type=candidate.relation_type,
                    relation_reason=candidate.reason,
                    score=candidate.score,
                    created_by="agent",
                )
            )
            relations.append(
                MemoryRelation(
                    user_id=user_id,
                    from_memory_id=candidate.memory.id,
                    to_memory_id=memory.id,
                    relation_type=candidate.relation_type,
                    relation_reason=candidate.reason,
                    score=candidate.score,
                    created_by="agent",
                )
            )
        return memory_relation_repository.create_many(db, relations)

    def backfill_all_users(self, db: Session, *, limit_per_memory: int = 8) -> int:
        rebuilt = 0
        memories = memory_repository.list_all_active(db)
        for memory in memories:
            self.rebuild_for_memory(db, memory.user_id, memory, limit=limit_per_memory)
            rebuilt += 1
        return rebuilt

    def _facts_by_memory(self, db: Session, user_id: uuid.UUID) -> dict[uuid.UUID, list[ExtractedFact]]:
        facts_by_memory: dict[uuid.UUID, list[ExtractedFact]] = {}
        for fact in fact_repository.list_for_user(db, user_id):
            facts_by_memory.setdefault(fact.memory_id, []).append(fact)
        return facts_by_memory

    def _rank_candidates(
        self,
        memory: MemoryItem,
        all_memories: list[MemoryItem],
        facts_by_memory: dict[uuid.UUID, list[ExtractedFact]],
    ) -> list[RelationCandidate]:
        target_terms = _memory_terms(memory)
        target_fact_terms = _fact_terms(facts_by_memory.get(memory.id, []))
        candidates: list[RelationCandidate] = []

        for candidate in all_memories:
            if candidate.id == memory.id:
                continue
            candidate_terms = _memory_terms(candidate)
            candidate_fact_terms = _fact_terms(facts_by_memory.get(candidate.id, []))
            shared_terms = target_terms & candidate_terms
            shared_fact_terms = target_fact_terms & candidate_fact_terms
            shared_entities = _string_set(memory.entities) & _string_set(candidate.entities)
            same_category = bool(memory.category and memory.category == candidate.category)
            time_score = _temporal_score(memory.event_time, candidate.event_time)
            if (shared_terms or shared_fact_terms or shared_entities or same_category) and (
                _has_negative_relation_marker(memory) or _has_negative_relation_marker(candidate)
            ):
                continue

            score = 0.0
            score += min(len(shared_terms), 5) * 0.1
            score += min(len(shared_fact_terms), 4) * 0.18
            score += 0.14 if same_category else 0.0
            score += time_score
            score += min(len(shared_entities), 4) * 0.16
            score = round(min(score, 0.98), 4)
            if score < 0.18:
                continue

            relation_type, reason = _best_relation_type(
                shared_terms=shared_terms,
                shared_fact_terms=shared_fact_terms,
                shared_entities=shared_entities,
                same_category=same_category,
                temporal_score=time_score,
            )
            candidates.append(
                RelationCandidate(
                    memory=candidate,
                    relation_type=relation_type,
                    reason=reason,
                    score=score,
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates


memory_relation_service = MemoryRelationService()
