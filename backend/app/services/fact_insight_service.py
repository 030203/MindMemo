from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import uuid

from sqlalchemy.orm import Session

from app.models.memory import ExtractedFact
from app.repos.fact_repo import fact_repository
from app.repos.memory_repo import memory_repository
from app.schemas.qa import CitationItem


@dataclass(frozen=True)
class FactInsight:
    answer: str
    citations: list[CitationItem]
    suggested_followups: list[str]


@dataclass(frozen=True)
class TimeWindow:
    label: str
    start: datetime | None
    end: datetime | None


class FactInsightService:
    def answer_question(self, db: Session, user_id: uuid.UUID, question: str) -> FactInsight | None:
        normalized_question = question.strip()
        if not normalized_question:
            return None

        intent = self._detect_intent(normalized_question)
        if intent is None:
            return None

        window = self._resolve_time_window(normalized_question)
        facts = self._filter_by_time(fact_repository.list_for_user(db, user_id, fact_type=intent), window)
        if intent == "learning":
            facts = self._filter_learning_by_query_terms(facts, normalized_question)

        citations = self._build_citations(db, user_id, facts)
        if intent == "expense":
            return self._build_expense_answer(facts, citations, window)
        if intent == "mood":
            return self._build_mood_answer(facts, citations, window)
        if intent == "learning":
            return self._build_learning_answer(facts, citations, window)
        if intent == "plan":
            return self._build_plan_answer(facts, citations, window)
        return None

    def _detect_intent(self, question: str) -> str | None:
        lowered = question.lower()
        if any(marker in question for marker in ["\u82b1\u4e86", "\u6d88\u8d39", "\u5f00\u9500", "\u652f\u51fa", "\u82b1\u8d39", "\u591a\u5c11\u94b1", "\u4e70\u4e86", "\u82b1\u94b1"]):
            return "expense"
        if any(marker in question for marker in ["\u60c5\u7eea", "\u5fc3\u60c5", "\u72b6\u6001", "\u7761\u7720", "\u7761\u5f97", "\u538b\u529b", "\u7126\u8651", "\u7d2f\u4e0d\u7d2f"]):
            return "mood"
        if any(marker in question for marker in ["\u8ba1\u5212", "\u5f85\u529e", "\u5b89\u6392", "\u63d0\u9192", "\u8981\u505a", "\u6ca1\u5904\u7406", "\u8bb0\u5f97"]):
            return "plan"
        if any(marker in question for marker in ["\u5b66\u4e60", "\u7814\u7a76", "\u6280\u672f", "\u4e3b\u9898", "\u8bba\u6587", "\u67b6\u6784", "\u63d0\u5230", "\u5185\u5bb9"]):
            return "learning"
        if any(token in lowered for token in ["rag", "agent", "roomos", "langgraph", "pgvector", "workflow", "embedding"]):
            return "learning"
        return None

    def _build_expense_answer(self, facts: list[ExtractedFact], citations: list[CitationItem], window: TimeWindow) -> FactInsight:
        expense_facts = [fact for fact in facts if self._amount(fact) is not None]
        if not expense_facts:
            return FactInsight(
                answer=f"{window.label}\u6211\u8fd8\u6ca1\u6709\u627e\u5230\u53ef\u7edf\u8ba1\u7684\u6d88\u8d39\u8bb0\u5f55\u3002",
                citations=[],
                suggested_followups=["\u6211\u6700\u8fd1\u6709\u54ea\u4e9b\u5f00\u9500\uff1f", "\u6211\u4e0a\u4e2a\u6708\u5728\u54ea\u65b9\u9762\u82b1\u94b1\u6700\u591a\uff1f"],
            )

        total = sum(self._amount(fact) or 0 for fact in expense_facts)
        category_totals: defaultdict[str, float] = defaultdict(float)
        for fact in expense_facts:
            category_totals[self._category(fact)] += self._amount(fact) or 0
        top_category, top_amount = max(category_totals.items(), key=lambda item: item[1])
        average = total / max(len(expense_facts), 1)
        anomaly = next(
            (
                (fact, self._amount(fact) or 0.0)
                for fact in sorted(expense_facts, key=lambda item: self._amount(item) or 0.0, reverse=True)
                if (self._amount(fact) or 0.0) >= max(average * 1.8, 80.0)
            ),
            None,
        )
        breakdown = "\uff1b".join(
            f"{self._category_label(category)} {amount:g} CNY"
            for category, amount in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)
        )
        answer = (
            f"{window.label}\u6211\u4ece\u7ed3\u6784\u5316\u6d88\u8d39\u8bb0\u5f55\u91cc\u7edf\u8ba1\u5230 {len(expense_facts)} \u7b14\u652f\u51fa\uff0c\u603b\u8ba1 {total:g} CNY\u3002\n\n"
            f"\u82b1\u8d39\u6700\u591a\u7684\u662f{self._category_label(top_category)}\uff0c\u7ea6 {top_amount:g} CNY\u3002\n\n"
            f"\u5206\u7c7b\u62c6\u89e3\uff1a{breakdown}\u3002"
        )
        if anomaly is not None:
            fact, amount = anomaly
            raw_text = str(self._payload(fact).get("raw_text") or fact.title)
            answer = f"{answer}\n\n\u5f02\u5e38\u63d0\u793a\uff1a{amount:g} CNY \u8fd9\u7b14\u652f\u51fa\u660e\u663e\u9ad8\u4e8e\u672c\u6708\u5e73\u5747\u6c34\u5e73\uff0c\u53ef\u4ee5\u56de\u770b\uff1a{raw_text}\u3002"
        return FactInsight(
            answer=answer,
            citations=citations,
            suggested_followups=["\u628a\u6700\u8fd1\u6d88\u8d39\u6309\u7c7b\u522b\u5217\u51fa\u6765", "\u6211\u4e0a\u4e2a\u6708\u5728\u54ea\u65b9\u9762\u82b1\u94b1\u6700\u591a\uff1f", "\u6700\u8fd1\u5f00\u9500\u6709\u6ca1\u6709\u5f02\u5e38\uff1f"],
        )

    def _build_mood_answer(self, facts: list[ExtractedFact], citations: list[CitationItem], window: TimeWindow) -> FactInsight:
        mood_facts = [fact for fact in facts if self._payload(fact).get("valence") is not None]
        if not mood_facts:
            return FactInsight(
                answer=f"{window.label}\u6211\u8fd8\u6ca1\u6709\u627e\u5230\u8db3\u591f\u7684\u60c5\u7eea\u6216\u7761\u7720\u72b6\u6001\u8bb0\u5f55\u3002",
                citations=[],
                suggested_followups=["\u6211\u6700\u8fd1\u7761\u7720\u600e\u4e48\u6837\uff1f", "\u6700\u8fd1\u8ba9\u6211\u538b\u529b\u5927\u7684\u4e8b\u60c5\u6709\u54ea\u4e9b\uff1f"],
            )

        values = [float(self._payload(fact).get("valence", 0)) for fact in mood_facts]
        average = sum(values) / len(values)
        if average <= -0.35:
            trend = "\u504f\u4f4e\uff0c\u4f11\u606f\u3001\u7761\u7720\u6216\u538b\u529b\u4fe1\u53f7\u6bd4\u8f83\u660e\u663e"
        elif average < 0.15:
            trend = "\u7565\u6709\u6ce2\u52a8\uff0c\u6574\u4f53\u8fd8\u6ca1\u6709\u5f62\u6210\u7a33\u5b9a\u79ef\u6781\u4fe1\u53f7"
        else:
            trend = "\u504f\u79ef\u6781\uff0c\u72b6\u6001\u8bb0\u5f55\u91cc\u51fa\u73b0\u4e86\u66f4\u591a\u6b63\u5411\u4fe1\u53f7"
        labels = Counter(str(self._payload(fact).get("label") or fact.title) for fact in mood_facts)
        label_summary = "\u3001".join(f"{label} x{count}" for label, count in labels.most_common(4))
        answer = f"{window.label}\u6211\u627e\u5230 {len(mood_facts)} \u6761\u60c5\u7eea/\u72b6\u6001\u4fe1\u53f7\uff0c\u6574\u4f53\u8d8b\u52bf{trend}\u3002\n\n\u4e3b\u8981\u4fe1\u53f7\uff1a{label_summary}\u3002"
        return FactInsight(
            answer=answer,
            citations=citations,
            suggested_followups=["\u6700\u8fd1\u8ba9\u6211\u538b\u529b\u5927\u7684\u4e8b\u60c5\u6709\u54ea\u4e9b\uff1f", "\u6211\u6700\u8fd1\u7761\u7720\u600e\u4e48\u6837\uff1f", "\u628a\u6700\u8fd1\u60c5\u7eea\u6309\u65f6\u95f4\u7ebf\u5217\u51fa\u6765"],
        )

    def _build_learning_answer(self, facts: list[ExtractedFact], citations: list[CitationItem], window: TimeWindow) -> FactInsight:
        if not facts:
            return FactInsight(
                answer=f"{window.label}\u6211\u8fd8\u6ca1\u6709\u627e\u5230\u8db3\u591f\u7684\u5b66\u4e60/\u7814\u7a76\u4e8b\u5b9e\u3002",
                citations=[],
                suggested_followups=["\u6211\u6700\u8fd1\u5728\u7814\u7a76\u54ea\u4e9b\u6280\u672f\uff1f", "\u548c RAG \u76f8\u5173\u7684\u8bb0\u5f55\u6709\u54ea\u4e9b\uff1f"],
            )

        topics: Counter[str] = Counter()
        for fact in facts:
            for topic in self._payload(fact).get("topics") or []:
                if str(topic).strip():
                    topics[str(topic).strip()] += 1
        if topics:
            topic_summary = "\u3001".join(f"{topic} x{count}" for topic, count in topics.most_common(8))
            answer = f"{window.label}\u4f60\u7684\u5b66\u4e60/\u7814\u7a76\u4e3b\u7ebf\u4e3b\u8981\u96c6\u4e2d\u5728\uff1a{topic_summary}\u3002\n\n\u6211\u53c2\u8003\u4e86 {len(facts)} \u6761\u7ed3\u6784\u5316\u5b66\u4e60\u4e8b\u5b9e\u3002"
        else:
            answer = f"{window.label}\u6211\u627e\u5230 {len(facts)} \u6761\u5b66\u4e60/\u7814\u7a76\u76f8\u5173\u8bb0\u5f55\uff0c\u4f46\u8fd8\u6ca1\u6709\u62bd\u53d6\u51fa\u7a33\u5b9a\u4e3b\u9898\u8bcd\u3002"
        snippets = [
            str(self._payload(fact).get("raw_text") or fact.title).strip()
            for fact in facts[:3]
            if str(self._payload(fact).get("raw_text") or fact.title).strip()
        ]
        if snippets and len(facts) <= 3:
            answer = f"{answer}\n\n\u5173\u952e\u8bb0\u5f55\uff1a" + "\uff1b".join(snippets)
        return FactInsight(
            answer=answer,
            citations=citations,
            suggested_followups=["\u548c RAG \u76f8\u5173\u7684\u8bb0\u5f55\u6709\u54ea\u4e9b\uff1f", "\u6700\u8fd1\u63d0\u5230 RoomOS \u7684\u5185\u5bb9\u6709\u54ea\u4e9b\uff1f", "\u628a\u6700\u8fd1\u5b66\u4e60\u5185\u5bb9\u603b\u7ed3\u6210\u8def\u7ebf\u56fe"],
        )

    def _build_plan_answer(self, facts: list[ExtractedFact], citations: list[CitationItem], window: TimeWindow) -> FactInsight:
        if not facts:
            return FactInsight(
                answer=f"{window.label}\u6211\u8fd8\u6ca1\u6709\u627e\u5230\u660e\u786e\u7684\u8ba1\u5212\u6216\u5f85\u529e\u5019\u9009\u3002",
                citations=[],
                suggested_followups=["\u6700\u8fd1\u6709\u54ea\u4e9b\u4e8b\u4e00\u76f4\u6ca1\u5904\u7406\uff1f", "\u628a\u6700\u8fd1\u8ba1\u5212\u6309\u65f6\u95f4\u5217\u51fa\u6765"],
            )

        ordered = sorted(facts, key=self._fact_sort_time)
        lines = []
        for index, fact in enumerate(ordered[:5], start=1):
            due_time = self._payload(fact).get("due_time")
            raw_text = str(self._payload(fact).get("raw_text") or fact.title)
            due_label = f"\uff08\u9884\u8ba1\u65f6\u95f4\uff1a{due_time}\uff09" if due_time else ""
            lines.append(f"{index}. {raw_text}{due_label}")
        answer = f"{window.label}\u6211\u627e\u5230 {len(facts)} \u6761\u8ba1\u5212/\u5f85\u529e\u5019\u9009\uff1a\n\n" + "\n".join(lines)
        return FactInsight(
            answer=answer,
            citations=citations,
            suggested_followups=["\u628a\u6700\u8fd1\u8ba1\u5212\u6309\u65f6\u95f4\u5217\u51fa\u6765", "\u54ea\u4e9b\u8ba1\u5212\u9700\u8981\u63d0\u9192\uff1f", "\u5e2e\u6211\u628a\u8fd9\u4e9b\u8ba1\u5212\u8f6c\u6210\u5f85\u529e"],
        )

    def _filter_by_time(self, facts: list[ExtractedFact], window: TimeWindow) -> list[ExtractedFact]:
        if window.start is None and window.end is None:
            return facts
        filtered = []
        for fact in facts:
            event_time = self._as_utc(fact.event_time or fact.created_at)
            if event_time is None:
                continue
            if window.start is not None and event_time < window.start:
                continue
            if window.end is not None and event_time >= window.end:
                continue
            filtered.append(fact)
        return filtered

    def _filter_learning_by_query_terms(self, facts: list[ExtractedFact], question: str) -> list[ExtractedFact]:
        terms = self._query_topic_terms(question)
        if any(marker in question for marker in ["\u6307\u6807", "\u8bc4\u4f30", "\u8861\u91cf"]):
            metric_terms = ["recall", "mrr", "precision", "evaluation", "\u8bc4\u4f30", "\u6307\u6807"]
            metric_facts = []
            for fact in facts:
                payload = self._payload(fact)
                haystack = " ".join(
                    [
                        str(payload.get("raw_text") or ""),
                        fact.title,
                        *[str(topic) for topic in payload.get("topics") or []],
                    ]
                ).lower()
                if any(term.lower() in haystack for term in metric_terms):
                    metric_facts.append(fact)
            if metric_facts:
                return metric_facts
        if not terms:
            return facts
        matched = []
        for fact in facts:
            payload = self._payload(fact)
            raw_text = str(payload.get("raw_text") or "")
            topics = [str(topic) for topic in payload.get("topics") or []]
            haystack = " ".join([raw_text, fact.title, *topics]).lower()
            if any(term.lower() in haystack for term in terms):
                matched.append(fact)
        return matched

    def _query_topic_terms(self, question: str) -> list[str]:
        known_terms = ["RAG", "Agent", "RoomOS", "LangGraph", "pgvector", "Workflow", "embedding"]
        terms = [term for term in known_terms if term.lower() in question.lower()]
        if terms:
            return terms
        if "\u54ea\u4e9b" in question or "\u4ec0\u4e48" in question:
            return []
        return [token for token in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", question) if token.lower() not in {"cny"}]

    def _build_citations(self, db: Session, user_id: uuid.UUID, facts: list[ExtractedFact]) -> list[CitationItem]:
        citations: list[CitationItem] = []
        seen_memory_ids: set[uuid.UUID] = set()
        for fact in facts:
            if fact.memory_id in seen_memory_ids:
                continue
            memory = memory_repository.get_for_user(db, user_id, fact.memory_id)
            if memory is None:
                continue
            seen_memory_ids.add(fact.memory_id)
            payload = self._payload(fact)
            citations.append(
                CitationItem(
                    type="memory",
                    id=str(memory.id),
                    title=memory.title or "Untitled Memory",
                    snippet=str(payload.get("raw_text") or memory.content_summary or ""),
                    score=float(fact.confidence_score),
                )
            )
            if len(citations) >= 4:
                break
        return citations

    def _resolve_time_window(self, question: str) -> TimeWindow:
        now = datetime.now(timezone.utc)
        today = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        if any(marker in question for marker in ["\u4eca\u5929", "\u4eca\u65e5"]):
            return TimeWindow("\u4eca\u5929\uff0c", today, today + timedelta(days=1))
        if "\u6628\u5929" in question:
            return TimeWindow("\u6628\u5929\uff0c", today - timedelta(days=1), today)
        if any(marker in question for marker in ["\u8fd9\u5468", "\u672c\u5468"]):
            start = today - timedelta(days=today.weekday())
            return TimeWindow("\u672c\u5468\uff0c", start, start + timedelta(days=7))
        if any(marker in question for marker in ["\u4e0a\u4e2a\u6708", "\u4e0a\u6708"]):
            first_day_this_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
            start = datetime(now.year - 1, 12, 1, tzinfo=timezone.utc) if now.month == 1 else datetime(now.year, now.month - 1, 1, tzinfo=timezone.utc)
            return TimeWindow("\u4e0a\u4e2a\u6708\uff0c", start, first_day_this_month)
        if any(marker in question for marker in ["\u8fd9\u4e2a\u6708", "\u672c\u6708", "\u8fd9\u6708"]):
            start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
            return TimeWindow("\u672c\u6708\uff0c", start, self._next_month(start))
        if "\u4eca\u5e74" in question:
            start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
            return TimeWindow("\u4eca\u5e74\uff0c", start, datetime(now.year + 1, 1, 1, tzinfo=timezone.utc))
        if any(marker in question for marker in ["\u6700\u8fd1", "\u8fd1\u671f"]):
            return TimeWindow("\u6700\u8fd130\u5929\uff0c", now - timedelta(days=30), now + timedelta(seconds=1))
        return TimeWindow("", None, None)

    def _next_month(self, start: datetime) -> datetime:
        if start.month == 12:
            return datetime(start.year + 1, 1, 1, tzinfo=timezone.utc)
        return datetime(start.year, start.month + 1, 1, tzinfo=timezone.utc)

    def _fact_sort_time(self, fact: ExtractedFact) -> datetime:
        due_time = self._payload(fact).get("due_time")
        if isinstance(due_time, str) and due_time:
            try:
                parsed_due_time = datetime.fromisoformat(due_time.replace("Z", "+00:00"))
                return self._as_utc(parsed_due_time) or datetime.max.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return self._as_utc(fact.event_time or fact.created_at) or datetime.max.replace(tzinfo=timezone.utc)

    def _as_utc(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _payload(self, fact: ExtractedFact) -> dict:
        return dict(fact.structured_payload or {})

    def _amount(self, fact: ExtractedFact) -> float | None:
        amount = self._payload(fact).get("amount")
        if amount is None:
            return None
        try:
            return float(amount)
        except (TypeError, ValueError):
            return None

    def _category(self, fact: ExtractedFact) -> str:
        return str(self._payload(fact).get("category") or "other")

    def _category_label(self, category: str) -> str:
        return {
            "electronics": "\u6570\u7801/\u7535\u5b50",
            "food": "\u9910\u996e",
            "transport": "\u4ea4\u901a",
            "housing": "\u5c45\u4f4f",
            "learning": "\u5b66\u4e60",
            "other": "\u5176\u4ed6",
        }.get(category, category)


fact_insight_service = FactInsightService()
