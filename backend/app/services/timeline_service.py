from datetime import datetime, timezone
import uuid

from sqlalchemy.orm import Session

from app.models.memory import ExtractedFact
from app.repos.fact_repo import fact_repository
from app.repos.timeline_repo import timeline_repository
from app.schemas.timeline import MemorySignalResponse, TimelineEventResponse


class TimelineService:
    def list_timeline(self, db: Session, user_id: uuid.UUID) -> list[TimelineEventResponse]:
        events = timeline_repository.list_for_user(db, user_id)
        return [
            TimelineEventResponse(
                id=str(event.id),
                title=event.title,
                summary=event.summary or "",
                event_type=event.event_type,
                event_time=event.event_time,
            )
            for event in events
        ]

    def list_memory_signals(
        self,
        db: Session,
        user_id: uuid.UUID,
        fact_type: str | None = None,
    ) -> list[MemorySignalResponse]:
        facts = fact_repository.list_for_user(db, user_id, fact_type=fact_type)
        return [self._to_memory_signal(fact) for fact in facts]

    def _to_memory_signal(self, fact: ExtractedFact) -> MemorySignalResponse:
        payload = dict(fact.structured_payload or {})
        return MemorySignalResponse(
            id=str(fact.id),
            memory_id=str(fact.memory_id),
            fact_type=fact.fact_type,
            title=fact.title,
            summary=self._build_signal_summary(fact, payload),
            event_time=fact.event_time or fact.created_at or datetime.now(timezone.utc),
            confidence_score=float(fact.confidence_score),
            tone=self._tone_for_fact(fact, payload),
            metadata=payload,
        )

    def _build_signal_summary(self, fact: ExtractedFact, payload: dict) -> str:
        if fact.fact_type == "expense":
            amount = payload.get("amount")
            currency = payload.get("currency") or "CNY"
            category = self._category_label(str(payload.get("category") or "other"))
            return f"{category}支出 {amount:g} {currency}" if isinstance(amount, (int, float)) else f"{category}支出"

        if fact.fact_type == "mood":
            label = payload.get("label") or fact.title
            valence = payload.get("valence")
            if isinstance(valence, (int, float)):
                direction = "正向" if valence > 0 else "负向" if valence < 0 else "中性"
                return f"{label} · {direction}状态信号"
            return f"{label} · 状态信号"

        if fact.fact_type == "learning":
            topics = [str(topic) for topic in payload.get("topics") or [] if str(topic).strip()]
            return f"研究主题：{'、'.join(topics[:4])}" if topics else "学习/研究相关记忆"

        if fact.fact_type == "plan":
            due_time = payload.get("due_time")
            return f"计划候选 · 预计时间 {due_time}" if due_time else "计划/待办候选"

        return str(payload.get("raw_text") or fact.title)

    def _tone_for_fact(self, fact: ExtractedFact, payload: dict) -> str:
        if fact.fact_type == "expense":
            return "blue"
        if fact.fact_type == "learning":
            return "cyan"
        if fact.fact_type == "plan":
            return "violet"
        if fact.fact_type == "mood":
            valence = payload.get("valence")
            if isinstance(valence, (int, float)) and valence > 0:
                return "green"
            if isinstance(valence, (int, float)) and valence < 0:
                return "amber"
            return "violet"
        return "neutral"

    def _category_label(self, category: str) -> str:
        return {
            "electronics": "数码/电子",
            "food": "餐饮",
            "transport": "交通",
            "housing": "居住",
            "learning": "学习",
            "other": "其他",
        }.get(category, category)


timeline_service = TimelineService()
