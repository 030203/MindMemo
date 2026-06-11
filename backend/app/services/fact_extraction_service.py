from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

from sqlalchemy.orm import Session

from app.models.memory import ExtractedFact, MemoryItem
from app.repos.fact_repo import fact_repository
from app.services.memory_understanding_service import extract_topics


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def localnow() -> datetime:
    return datetime.now()


@dataclass(frozen=True)
class FactCandidate:
    fact_type: str
    title: str
    structured_payload: dict
    confidence_score: float
    event_time: datetime | None = None


class FactExtractionService:
    """Small rule engine for Phase 7 memory intelligence.

    It is intentionally simple: these facts create a stable structured surface
    for later RAG, graph, and agent workflows without pretending to be a full
    NLP pipeline yet.
    """

    def rebuild_facts_for_memory(self, db: Session, memory: MemoryItem) -> int:
        facts = [
            ExtractedFact(
                user_id=memory.user_id,
                memory_id=memory.id,
                fact_type=candidate.fact_type,
                title=candidate.title,
                structured_payload=candidate.structured_payload,
                confidence_score=candidate.confidence_score,
                event_time=candidate.event_time or memory.event_time or memory.created_at or utcnow(),
                source="rule_v1",
            )
            for candidate in self.extract(memory)
        ]
        return fact_repository.replace_for_memory(db, memory.user_id, memory.id, facts)

    def extract_plan_metadata(self, content: str, reference_time: datetime | None = None) -> dict:
        event_time = self._infer_event_time(content, self._to_local_reference(reference_time))
        plans = self._extract_plan(content, event_time)
        due_time = None
        is_todo_candidate = False
        for plan in plans:
            is_todo_candidate = is_todo_candidate or bool(plan.structured_payload.get("todo_candidate"))
            raw_due_time = plan.structured_payload.get("due_time")
            if raw_due_time:
                due_time = datetime.fromisoformat(raw_due_time)
                break
        return {"is_todo_candidate": is_todo_candidate, "due_time": due_time}

    def extract(self, memory: MemoryItem) -> list[FactCandidate]:
        content = (memory.content_clean or memory.content_raw or "").strip()
        if not content:
            return []

        event_time = self._infer_event_time(content, self._to_local_reference(memory.event_time))
        candidates: list[FactCandidate] = []
        candidates.extend(self._extract_expense(content, event_time))
        candidates.extend(self._extract_mood(content, event_time))
        candidates.extend(self._extract_learning(content, event_time))
        candidates.extend(self._extract_plan(content, event_time))
        return self._deduplicate(candidates)

    def _extract_expense(self, content: str, event_time: datetime | None) -> list[FactCandidate]:
        amount_match = re.search(
            r"(?P<amount>\d+(?:\.\d+)?)\s*(?:\u5143|\u5757|cny|CNY|rmb|RMB|\u4eba\u6c11\u5e01)",
            content,
        )
        if not amount_match:
            return []

        amount = float(amount_match.group("amount"))
        category = self._infer_expense_category(content)
        return [
            FactCandidate(
                fact_type="expense",
                title=f"Expense {amount:g} CNY",
                structured_payload={
                    "amount": amount,
                    "currency": "CNY",
                    "category": category,
                    "raw_text": content,
                },
                confidence_score=0.86,
                event_time=event_time,
            )
        ]

    def _extract_mood(self, content: str, event_time: datetime | None) -> list[FactCandidate]:
        mood_keywords = {
            "\u7761\u5f97\u4e0d\u597d": ("sleep", "Poor sleep", -0.45),
            "\u5931\u7720": ("sleep", "Insomnia", -0.65),
            "\u7126\u8651": ("mood", "Anxiety", -0.55),
            "\u538b\u529b": ("mood", "High stress", -0.38),
            "\u5f00\u5fc3": ("mood", "Happy", 0.55),
            "\u75b2\u60eb": ("energy", "Fatigue", -0.45),
        }
        facts = []
        for keyword, (kind, label, valence) in mood_keywords.items():
            if keyword in content:
                facts.append(
                    FactCandidate(
                        fact_type="mood",
                        title=label,
                        structured_payload={
                            "kind": kind,
                            "label": label,
                            "valence": valence,
                            "raw_text": content,
                        },
                        confidence_score=0.78,
                        event_time=event_time,
                    )
                )
        return facts

    def _extract_learning(self, content: str, event_time: datetime | None) -> list[FactCandidate]:
        topics = extract_topics(content)
        learning_markers = [
            "\u7814\u7a76",
            "\u5b66\u4e60",
            "\u8bba\u6587",
            "\u6280\u672f",
            "\u67b6\u6784",
        ]
        if not topics and not any(word in content for word in learning_markers):
            return []

        return [
            FactCandidate(
                fact_type="learning",
                title=f"Learning topic: {topics[0] if topics else 'general'}",
                structured_payload={
                    "topics": list(dict.fromkeys(topics)),
                    "raw_text": content,
                },
                confidence_score=0.74 if topics else 0.62,
                event_time=event_time,
            )
        ]

    def _extract_plan(self, content: str, event_time: datetime | None) -> list[FactCandidate]:
        plan_markers = [
            "\u8bb0\u5f97",
            "\u63d0\u9192",
            "\u901a\u77e5",
            "\u53eb\u6211",
            "\u522b\u5fd8",
            "\u5230\u65f6\u5019",
            "\u4e0b\u4e2a\u6708",
            "\u660e\u5929",
            "\u4e0b\u5468",
            "\u6708\u5e95",
            "\u4ea4\u623f\u79df",
            "\u8981\u53bb",
            "\u9700\u8981",
        ]
        if not any(marker in content for marker in plan_markers):
            return []

        due_time = self._infer_due_time(content, event_time)
        todo_candidate = self._is_todo_candidate(content)
        return [
            FactCandidate(
                fact_type="plan",
                title="Plan / todo candidate",
                structured_payload={
                    "due_time": due_time.isoformat() if due_time else None,
                    "todo_candidate": todo_candidate,
                    "raw_text": content,
                },
                confidence_score=0.72,
                event_time=event_time,
            )
        ]

    def _infer_event_time(self, content: str, fallback: datetime | None) -> datetime | None:
        base = fallback or localnow()
        if "\u6628\u5929" in content:
            return base - timedelta(days=1)
        if "\u524d\u5929" in content:
            return base - timedelta(days=2)
        if "\u4eca\u5929" in content:
            return base
        return fallback

    def _infer_due_time(self, content: str, event_time: datetime | None) -> datetime | None:
        base = event_time or localnow()
        time_of_day = self._infer_time_of_day(content)
        if "\u660e\u5929" in content:
            due = base + timedelta(days=1)
            return self._with_time_of_day(due, time_of_day)
        if any(marker in content for marker in ["\u4eca\u5929", "\u4eca\u665a", "\u4eca\u65e5"]):
            due = self._with_time_of_day(base, time_of_day)
            if time_of_day is not None and due <= base:
                return due + timedelta(days=1)
            return due
        if "\u660e\u5929" in content:
            return base + timedelta(days=1)
        if "\u4e0b\u5468" in content:
            return self._with_time_of_day(base + timedelta(days=7), time_of_day)
        if "\u4e0b\u4e2a\u6708" in content:
            return self._with_time_of_day(base + timedelta(days=30), time_of_day)
        if time_of_day is not None:
            due = self._with_time_of_day(base, time_of_day)
            if due <= base:
                return due + timedelta(days=1)
            return due
        return None

    def _infer_time_of_day(self, content: str) -> tuple[int, int] | None:
        match = re.search(r"(?P<hour>\d{1,2})\s*(?:[:\uff1a]\s*(?P<minute>\d{1,2})|\u70b9(?P<cn_minute>\d{1,2})?\u5206?)?", content)
        if not match:
            return None

        hour = int(match.group("hour"))
        minute = int(match.group("minute") or match.group("cn_minute") or 0)
        if hour > 23 or minute > 59:
            return None
        if hour < 12 and any(marker in content for marker in ["\u4e0b\u5348", "\u665a\u4e0a", "\u4eca\u665a"]):
            hour += 12
        return hour, minute

    def _with_time_of_day(self, value: datetime, time_of_day: tuple[int, int] | None) -> datetime:
        if time_of_day is None:
            return value
        hour, minute = time_of_day
        return value.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def _to_local_reference(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone().replace(tzinfo=None)
        return value.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)

    def _is_todo_candidate(self, content: str) -> bool:
        explicit_reminder_markers = [
            "\u63d0\u9192\u6211",
            "\u63d0\u9192",
            "\u8bb0\u5f97",
            "\u522b\u5fd8",
            "\u901a\u77e5\u6211",
            "\u53eb\u6211",
            "\u5f85\u529e",
        ]
        lowered = content.lower()
        return any(marker in content for marker in explicit_reminder_markers) or "todo" in lowered

    def _infer_expense_category(self, content: str) -> str:
        category_keywords = {
            "electronics": [
                "\u8033\u673a",
                "\u7535\u8111",
                "\u624b\u673a",
                "\u952e\u76d8",
                "\u9f20\u6807",
            ],
            "food": [
                "\u996d",
                "\u5496\u5561",
                "\u5976\u8336",
                "\u5916\u5356",
                "\u9910",
            ],
            "transport": [
                "\u6253\u8f66",
                "\u5730\u94c1",
                "\u516c\u4ea4",
                "\u8f66\u7968",
            ],
            "housing": [
                "\u623f\u79df",
                "\u7269\u4e1a",
                "\u6c34\u8d39",
                "\u7535\u8d39",
            ],
            "learning": [
                "\u4e66",
                "\u8bfe\u7a0b",
                "\u4f1a\u5458",
                "\u8bba\u6587",
            ],
        }
        for category, keywords in category_keywords.items():
            if any(keyword in content for keyword in keywords):
                return category
        return "other"

    def _deduplicate(self, candidates: list[FactCandidate]) -> list[FactCandidate]:
        seen: set[tuple[str, str]] = set()
        result = []
        for candidate in candidates:
            key = (candidate.fact_type, candidate.title)
            if key in seen:
                continue
            seen.add(key)
            result.append(candidate)
        return result


fact_extraction_service = FactExtractionService()
