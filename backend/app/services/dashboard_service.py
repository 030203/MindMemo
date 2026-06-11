from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.memory import ExtractedFact, MemoryItem
from app.models.todo import TodoItem
from app.repos.fact_repo import fact_repository
from app.repos.memory_repo import memory_repository
from app.repos.reminder_repo import reminder_repository
from app.repos.review_repo import review_repository
from app.repos.todo_repo import todo_repository
from app.schemas.dashboard import DashboardInsights, DashboardOverview, InsightSourceItem, MemoryInsightCard, ReminderItem
from app.services.reminder_service import reminder_service


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class InsightCacheEntry:
    cards: list[MemoryInsightCard]
    expires_at: datetime
    created_at: datetime


class DashboardService:
    def __init__(self) -> None:
        self._insight_cache: dict[tuple[str, str], InsightCacheEntry] = {}
        self._insight_cache_lock = Lock()
        self._insight_cache_hits = 0
        self._insight_cache_misses = 0

    def get_overview(self, db: Session, user_id: uuid.UUID) -> DashboardOverview:
        todos = todo_repository.list_for_user(db, user_id)
        active_todos = [todo for todo in todos if todo.status != "done"]
        now = utcnow()
        overdue_todos = [
            todo
            for todo in active_todos
            if ensure_utc(todo.due_at) is not None and ensure_utc(todo.due_at) < now
        ]
        recent_memories = memory_repository.count_recent(db, user_id, utcnow() - timedelta(days=7))
        pending_reviews = len([item for item in review_repository.list_for_user(db, user_id) if item.status == "pending"])

        focus_titles = [todo.title for todo in active_todos[:2]]
        today_focus = "\uff0c".join(focus_titles) if focus_titles else "\u4eca\u5929\u6682\u65f6\u6ca1\u6709\u9ad8\u4f18\u5148\u7ea7\u4efb\u52a1\uff0c\u9002\u5408\u6574\u7406\u8bb0\u5f55\u548c\u56de\u987e\u8fdb\u5c55\u3002"

        return DashboardOverview(
            today_focus=today_focus,
            today_todos=len(active_todos),
            overdue_todos=len(overdue_todos),
            recent_memories=recent_memories,
            pending_reviews=pending_reviews,
            daily_summary="\u7cfb\u7edf\u4f1a\u5468\u671f\u6027\u626b\u63cf\u5f85\u529e\uff0c\u6301\u7eed\u751f\u6210\u63d0\u9192\u72b6\u6001\uff0c\u5e76\u4f18\u5148\u5173\u6ce8\u903e\u671f\u3001\u4e34\u8fd1\u622a\u6b62\u548c\u9ad8\u4f18\u5148\u7ea7\u4e8b\u9879\u3002",
        )

    def list_reminders(self, db: Session, user_id: uuid.UUID, limit: int = 5) -> list[ReminderItem]:
        reminder_service.sync_user_reminders(db, user_id)
        reminders = reminder_repository.list_for_user(db, user_id, active_only=True)[:limit]
        return [
            ReminderItem(
                type=item.reminder_type,
                level=item.level,
                title=item.title,
                message=item.message,
                todo_id=str(item.todo_id),
                due_at=item.due_at,
            )
            for item in reminders
        ]

    def get_insights(self, db: Session, user_id: uuid.UUID, window: str = "default") -> DashboardInsights:
        return DashboardInsights(cards=self._get_cached_insight_cards(db, user_id, window=window))

    def get_insight_overview(self, db: Session, user_id: uuid.UUID, window: str = "default") -> DashboardInsights:
        return self.get_insights(db, user_id, window=window)

    def get_expense_insights(self, db: Session, user_id: uuid.UUID, window: str = "default") -> DashboardInsights:
        cards = [card for card in self._get_cached_insight_cards(db, user_id, window=window) if card.kind == "expense"]
        return DashboardInsights(cards=cards)

    def get_reflection_insights(self, db: Session, user_id: uuid.UUID, window: str = "default") -> DashboardInsights:
        reflection_kinds = {"mood", "learning", "project", "plan"}
        cards = [card for card in self._get_cached_insight_cards(db, user_id, window=window) if card.kind in reflection_kinds]
        return DashboardInsights(cards=cards)

    def get_insight_card(
        self,
        db: Session,
        user_id: uuid.UUID,
        kind: str,
        window: str = "default",
    ) -> MemoryInsightCard | None:
        for card in self._get_cached_insight_cards(db, user_id, window=window):
            if card.kind == kind:
                return card
        return None

    def invalidate_insight_cache(self, user_id: uuid.UUID | None = None) -> int:
        with self._insight_cache_lock:
            if user_id is None:
                removed = len(self._insight_cache)
                self._insight_cache.clear()
                return removed

            user_key = str(user_id)
            keys = [key for key in self._insight_cache if key[0] == user_key]
            for key in keys:
                self._insight_cache.pop(key, None)
            return len(keys)

    def cache_stats(self) -> dict:
        with self._insight_cache_lock:
            return {
                "entries": len(self._insight_cache),
                "hits": self._insight_cache_hits,
                "misses": self._insight_cache_misses,
                "ttl_seconds": settings.insight_cache_ttl_seconds,
            }

    def _get_cached_insight_cards(self, db: Session, user_id: uuid.UUID, *, window: str = "default") -> list[MemoryInsightCard]:
        normalized_window = self._normalize_insight_window(window)
        ttl_seconds = max(int(settings.insight_cache_ttl_seconds), 0)
        if ttl_seconds <= 0:
            return self._build_insight_cards(db, user_id, window=normalized_window)

        now = utcnow()
        cache_key = (str(user_id), normalized_window)
        with self._insight_cache_lock:
            entry = self._insight_cache.get(cache_key)
            if entry is not None and entry.expires_at > now:
                self._insight_cache_hits += 1
                return self._copy_cards(entry.cards)
            if entry is not None:
                self._insight_cache.pop(cache_key, None)
            self._insight_cache_misses += 1

        cards = self._build_insight_cards(db, user_id, window=normalized_window)
        entry = InsightCacheEntry(
            cards=self._copy_cards(cards),
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        with self._insight_cache_lock:
            self._insight_cache[cache_key] = entry
        return self._copy_cards(cards)

    def _copy_cards(self, cards: list[MemoryInsightCard]) -> list[MemoryInsightCard]:
        return [card.model_copy(deep=True) for card in cards]

    def _normalize_insight_window(self, window: str) -> str:
        normalized = (window or "default").strip().lower()
        if normalized in {"default", "7d", "30d", "90d", "month", "all"}:
            return normalized
        return "default"

    def _build_insight_cards(self, db: Session, user_id: uuid.UUID, *, window: str = "default") -> list[MemoryInsightCard]:
        facts = fact_repository.list_for_user(db, user_id)
        now = utcnow()
        month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        recent_start = now - timedelta(days=30)
        month_end = now + timedelta(seconds=1)
        future_end = now + timedelta(days=90)
        expense_start, expense_end, expense_label = self._resolve_insight_window(
            window,
            now,
            default_start=month_start,
            default_end=month_end,
            default_label="\u672c\u6708",
        )
        recent_start, recent_end, recent_label = self._resolve_insight_window(
            window,
            now,
            default_start=recent_start,
            default_end=month_end,
            default_label="\u6700\u8fd130\u5929",
        )

        return [
            self._expense_card(
                db,
                user_id,
                self._facts_in_window(facts, "expense", expense_start, expense_end),
                expense_label,
            ),
            self._mood_card(db, user_id, self._facts_in_window(facts, "mood", recent_start, recent_end), recent_label),
            self._learning_card(
                db,
                user_id,
                self._facts_in_window(facts, "learning", recent_start, recent_end),
                recent_label,
            ),
            self._plan_card(db, user_id, self._facts_in_window(facts, "plan", None, future_end)),
            self._project_card(db, user_id, recent_start, recent_end, recent_label),
        ]

    def _resolve_insight_window(
        self,
        window: str,
        now: datetime,
        *,
        default_start: datetime | None,
        default_end: datetime | None,
        default_label: str,
    ) -> tuple[datetime | None, datetime | None, str]:
        normalized = (window or "default").strip().lower()
        if normalized == "7d":
            return now - timedelta(days=7), now + timedelta(seconds=1), "\u6700\u8fd17\u5929"
        if normalized == "30d":
            return now - timedelta(days=30), now + timedelta(seconds=1), "\u6700\u8fd130\u5929"
        if normalized == "90d":
            return now - timedelta(days=90), now + timedelta(seconds=1), "\u6700\u8fd190\u5929"
        if normalized == "month":
            return datetime(now.year, now.month, 1, tzinfo=timezone.utc), now + timedelta(seconds=1), "\u672c\u6708"
        if normalized == "all":
            return None, None, "\u5168\u90e8"
        return default_start, default_end, default_label

    def _expense_card(
        self,
        db: Session,
        user_id: uuid.UUID,
        facts: list[ExtractedFact],
        window_label: str,
    ) -> MemoryInsightCard:
        category_totals: defaultdict[str, float] = defaultdict(float)
        total = 0.0
        expense_entries: list[tuple[ExtractedFact, float]] = []
        for fact in facts:
            amount = self._amount(fact)
            if amount is None:
                continue
            total += amount
            expense_entries.append((fact, amount))
            category_totals[self._payload(fact).get("category") or "other"] += amount

        if total <= 0:
            return MemoryInsightCard(
                kind="expense",
                title=f"{window_label}\u6d88\u8d39",
                value="\u5f85\u5f62\u6210",
                detail="\u8bb0\u5f55\u201c\u4eca\u5929\u82b1\u4e86100\u5143\u4e70\u8033\u673a\u201d\u8fd9\u7c7b\u5185\u5bb9\u540e\uff0c\u6211\u4f1a\u81ea\u52a8\u7ed3\u5408\u91d1\u989d\u3001\u54c1\u7c7b\u548c\u5f02\u5e38\u6ce2\u52a8\u751f\u6210\u6d88\u8d39\u6d1e\u5bdf\u3002",
                tone="neutral",
                items=["\u8fd8\u6ca1\u6709\u53ef\u7edf\u8ba1\u7684\u6d88\u8d39\u8bb0\u5f55"],
                question="\u5e2e\u6211\u5206\u6790\u4e00\u4e0b\u672c\u6708\u6d88\u8d39\u6982\u51b5",
                sources=[],
            )

        breakdown = [
            f"{self._category_label(str(category))} {amount:g} CNY"
            for category, amount in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)[:3]
        ]
        average = total / max(len(expense_entries), 1)
        anomaly = next(
            (
                (fact, amount)
                for fact, amount in sorted(expense_entries, key=lambda item: item[1], reverse=True)
                if amount >= max(average * 1.8, 80.0)
            ),
            None,
        )
        detail = f"{window_label}\u5df2\u8bc6\u522b\u5230 {len(expense_entries)} \u7b14\u6d88\u8d39\u4fe1\u53f7\uff0c\u53ef\u4ee5\u76f4\u63a5\u7528\u4e8e\u6982\u51b5\u548c\u5f02\u5e38\u5206\u6790\u3002"
        items = breakdown or ["\u6682\u65f6\u8fd8\u6ca1\u6709\u8db3\u591f\u7684\u5206\u7c7b\u4fe1\u53f7"]
        if anomaly is not None:
            fact, amount = anomaly
            payload = self._payload(fact)
            anomaly_hint = str(payload.get("raw_text") or fact.title)
            items = [*items, f"\u5f02\u5e38\u63d0\u793a\uff1a{amount:g} CNY \u00b7 {anomaly_hint}"]
            detail = f"{detail}\u6211\u8fd8\u6807\u8bb0\u51fa\u4e86\u9ad8\u4e8e\u5e73\u5747\u6c34\u5e73\u7684\u652f\u51fa\uff0c\u65b9\u4fbf\u4f60\u56de\u770b\u3002"
        return MemoryInsightCard(
            kind="expense",
            title=f"{window_label}\u6d88\u8d39",
            value=f"{total:g} CNY",
            detail=detail,
            tone="blue",
            items=items,
            question="\u5e2e\u6211\u5206\u6790\u4e00\u4e0b\u672c\u6708\u6d88\u8d39\u6982\u51b5",
            sources=self._fact_sources(db, user_id, expense_entries, limit=3),
        )

    def _mood_card(
        self,
        db: Session,
        user_id: uuid.UUID,
        facts: list[ExtractedFact],
        window_label: str,
    ) -> MemoryInsightCard:
        mood_values = [float(self._payload(fact).get("valence")) for fact in facts if self._payload(fact).get("valence") is not None]
        if not mood_values:
            return MemoryInsightCard(
                kind="mood",
                title=f"{window_label}\u72b6\u6001",
                value="\u7b49\u5f85\u4fe1\u53f7",
                detail="\u8bb0\u5f55\u7761\u7720\u3001\u538b\u529b\u3001\u5f00\u5fc3\u6216\u75b2\u60eb\uff0c\u6211\u4f1a\u9010\u6b65\u5f62\u6210\u72b6\u6001\u8d8b\u52bf\u3002",
                tone="neutral",
                items=["\u8fd8\u6ca1\u6709\u8db3\u591f\u7684\u60c5\u7eea/\u72b6\u6001\u4e8b\u5b9e"],
                question="\u6211\u6700\u8fd1\u60c5\u7eea\u600e\u4e48\u6837\uff1f",
                sources=[],
            )

        average = sum(mood_values) / len(mood_values)
        if average <= -0.35:
            value = "\u504f\u4f4e"
            tone = "amber"
        elif average < 0.15:
            value = "\u6709\u6ce2\u52a8"
            tone = "violet"
        else:
            value = "\u504f\u79ef\u6781"
            tone = "green"

        labels = Counter(str(self._payload(fact).get("label") or fact.title) for fact in facts)
        return MemoryInsightCard(
            kind="mood",
            title=f"{window_label}\u72b6\u6001",
            value=value,
            detail=f"{window_label}\u8bc6\u522b\u5230 {len(mood_values)} \u6761\u72b6\u6001\u4fe1\u53f7\u3002",
            tone=tone,
            items=[f"{label} x{count}" for label, count in labels.most_common(3)],
            question="\u6211\u6700\u8fd1\u60c5\u7eea\u600e\u4e48\u6837\uff1f",
            sources=self._fact_sources(db, user_id, facts, limit=3),
        )

    def _learning_card(
        self,
        db: Session,
        user_id: uuid.UUID,
        facts: list[ExtractedFact],
        window_label: str,
    ) -> MemoryInsightCard:
        topics: Counter[str] = Counter()
        for fact in facts:
            for topic in self._payload(fact).get("topics") or []:
                normalized = str(topic).strip()
                if normalized:
                    topics[normalized] += 1

        if not topics:
            return MemoryInsightCard(
                kind="learning",
                title=f"{window_label}\u7814\u7a76\u4e3b\u7ebf",
                value="\u5f85\u5f62\u6210",
                detail="\u8bb0\u5f55\u6b63\u5728\u7814\u7a76\u7684\u6280\u672f\u3001\u8bba\u6587\u548c\u9879\u76ee\u540e\uff0c\u6211\u4f1a\u6c89\u6dc0\u957f\u671f\u4e3b\u9898\u3002",
                tone="neutral",
                items=["\u8fd8\u6ca1\u6709\u7a33\u5b9a\u7814\u7a76\u4e3b\u9898"],
                question="\u6211\u6700\u8fd1\u5728\u7814\u7a76\u54ea\u4e9b\u6280\u672f\uff1f",
                sources=[],
            )

        top_topic = topics.most_common(1)[0][0]
        return MemoryInsightCard(
            kind="learning",
            title=f"{window_label}\u7814\u7a76\u4e3b\u7ebf",
            value=top_topic,
            detail=f"{window_label}\u8bc6\u522b\u5230 {len(facts)} \u6761\u5b66\u4e60/\u7814\u7a76\u4e8b\u5b9e\u3002",
            tone="cyan",
            items=[f"{topic} x{count}" for topic, count in topics.most_common(4)],
            question="\u6211\u6700\u8fd1\u5728\u7814\u7a76\u54ea\u4e9b\u6280\u672f\uff1f",
            sources=self._fact_sources(db, user_id, facts, limit=3),
        )

    def _plan_card(self, db: Session, user_id: uuid.UUID, facts: list[ExtractedFact]) -> MemoryInsightCard:
        if not facts:
            return MemoryInsightCard(
                kind="plan",
                title="\u8ba1\u5212\u5019\u9009",
                value="\u6682\u65e0",
                detail="\u8bb0\u5f55\u201c\u4e0b\u4e2a\u6708\u8bb0\u5f97\u4ea4\u623f\u79df\u201d\u540e\uff0c\u6211\u4f1a\u628a\u5b83\u8bc6\u522b\u4e3a\u8ba1\u5212\u5019\u9009\u3002",
                tone="neutral",
                items=["\u8fd8\u6ca1\u6709\u8ba1\u5212/\u5f85\u529e\u5019\u9009"],
                question="\u6700\u8fd1\u6709\u54ea\u4e9b\u8ba1\u5212/\u5f85\u529e\uff1f",
                sources=[],
            )

        items = []
        for fact in facts[:4]:
            payload = self._payload(fact)
            raw_text = str(payload.get("raw_text") or fact.title)
            due_time = payload.get("due_time")
            items.append(f"{raw_text} \u00b7 {due_time}" if due_time else raw_text)

        return MemoryInsightCard(
            kind="plan",
            title="\u8ba1\u5212\u5019\u9009",
            value=f"{len(facts)} \u6761",
            detail="\u8fd9\u4e9b\u6765\u81ea\u81ea\u7136\u8bed\u8a00\u91cc\u7684\u8ba1\u5212\u3001\u63d0\u9192\u548c\u5f85\u529e\u4fe1\u53f7\u3002",
            tone="violet",
            items=items,
            question="\u6700\u8fd1\u6709\u54ea\u4e9b\u8ba1\u5212/\u5f85\u529e\uff1f",
            sources=self._fact_sources(db, user_id, facts, limit=3),
        )

    def _project_card(
        self,
        db: Session,
        user_id: uuid.UUID,
        start: datetime | None,
        end: datetime | None,
        window_label: str,
    ) -> MemoryInsightCard:
        project_memories = memory_repository.list_for_user(db, user_id, category="project")
        todos = todo_repository.list_for_user(db, user_id)
        recent_projects = []
        for memory in project_memories:
            event_time = ensure_utc(memory.event_time or memory.created_at)
            if event_time is None:
                continue
            if start is not None and event_time < start:
                continue
            if end is not None and event_time >= end:
                continue
            recent_projects.append(memory)
        active_project_todos = [todo for todo in todos if todo.status != "done" and self._is_project_todo(todo)]

        if not recent_projects and not active_project_todos:
            return MemoryInsightCard(
                kind="project",
                title="\u9879\u76ee\u63a8\u8fdb",
                value="\u5f85\u5f62\u6210",
                detail="\u8bb0\u5f55\u9879\u76ee\u8fdb\u5c55\u3001\u91cc\u7a0b\u7891\u548c\u963b\u585e\u70b9\u540e\uff0c\u6211\u4f1a\u9010\u6b65\u5f62\u6210\u9879\u76ee\u6d1e\u5bdf\u3002",
                tone="neutral",
                items=["\u6700\u8fd1\u8fd8\u6ca1\u6709\u8db3\u591f\u7684\u9879\u76ee\u578b\u8bb0\u5f55"],
                question="\u6700\u8fd1\u9879\u76ee\u8fdb\u5c55\u600e\u4e48\u6837\uff1f",
                sources=[],
            )

        topic_counter: Counter[str] = Counter()
        for memory in recent_projects:
            for token in [*(memory.entities or []), *(memory.keywords or []), *(memory.tags or [])]:
                normalized = str(token).strip()
                if normalized:
                    topic_counter[normalized] += 1

        top_topic = self._project_focus(topic_counter, recent_projects, active_project_todos)
        blocked_or_risky = [
            todo
            for todo in active_project_todos
            if todo.status == "blocked" or todo.risk_level in {"high", "medium"} or todo.priority in {"high", "urgent"}
        ]
        next_steps = [(todo.title or "\u672a\u547d\u540d\u4efb\u52a1").strip() for todo in active_project_todos[:2]]
        items = [
            (memory.title or memory.content_summary or "\u672a\u547d\u540d\u9879\u76ee\u8bb0\u5f55").strip()
            for memory in recent_projects[:4]
        ]
        if blocked_or_risky:
            items.append(f"\u98ce\u9669/\u963b\u585e\uff1a{blocked_or_risky[0].title}")
        elif next_steps:
            items.append(f"\u4e0b\u4e00\u6b65\uff1a{next_steps[0]}")
        return MemoryInsightCard(
            kind="project",
            title="\u9879\u76ee\u63a8\u8fdb",
            value=top_topic,
            detail=(
                f"{window_label}\u8bc6\u522b\u5230 {len(recent_projects)} \u6761\u9879\u76ee\u578b\u8bb0\u5f55"
                f"\uff0c\u5e76\u4e32\u8054 {len(active_project_todos)} \u6761\u672a\u5b8c\u6210\u4efb\u52a1\uff0c\u7528\u4e8e\u603b\u7ed3\u4e3b\u7ebf\u3001\u98ce\u9669\u548c\u4e0b\u4e00\u6b65\u3002"
            ),
            tone="amber",
            items=items,
            question="\u6700\u8fd1\u9879\u76ee\u8fdb\u5c55\u600e\u4e48\u6837\uff1f",
            sources=self._project_sources(recent_projects, active_project_todos, limit=4),
        )

    def _facts_in_window(
        self,
        facts: list[ExtractedFact],
        fact_type: str,
        start: datetime | None,
        end: datetime | None,
    ) -> list[ExtractedFact]:
        matched = []
        for fact in facts:
            if fact.fact_type != fact_type:
                continue
            event_time = ensure_utc(fact.event_time or fact.created_at)
            if event_time is None:
                continue
            if start is not None and event_time < start:
                continue
            if end is not None and event_time >= end:
                continue
            matched.append(fact)
        return matched

    def _fact_sources(
        self,
        db: Session,
        user_id: uuid.UUID,
        facts: list[ExtractedFact] | list[tuple[ExtractedFact, float]],
        *,
        limit: int,
    ) -> list[InsightSourceItem]:
        sources: list[InsightSourceItem] = []
        seen_memory_ids: set[uuid.UUID] = set()
        for item in facts:
            fact = item[0] if isinstance(item, tuple) else item
            if fact.memory_id in seen_memory_ids:
                continue
            memory = memory_repository.get_for_user(db, user_id, fact.memory_id)
            if memory is None:
                continue
            seen_memory_ids.add(fact.memory_id)
            payload = self._payload(fact)
            snippet = str(payload.get("raw_text") or memory.content_summary or fact.title or "")
            sources.append(
                InsightSourceItem(
                    type="memory",
                    id=str(memory.id),
                    title=memory.title or "\u672a\u547d\u540d\u8bb0\u5f55",
                    snippet=snippet[:200],
                    event_time=memory.event_time or fact.event_time or memory.created_at,
                )
            )
            if len(sources) >= limit:
                break
        return sources

    def _project_sources(
        self,
        recent_projects: list[MemoryItem],
        active_project_todos: list[TodoItem],
        *,
        limit: int,
    ) -> list[InsightSourceItem]:
        sources: list[InsightSourceItem] = []
        for memory in recent_projects[:limit]:
            sources.append(
                InsightSourceItem(
                    type="memory",
                    id=str(memory.id),
                    title=memory.title or "\u672a\u547d\u540d\u9879\u76ee\u8bb0\u5f55",
                    snippet=(memory.content_summary or memory.content_clean or memory.content_raw or "")[:200],
                    event_time=memory.event_time or memory.created_at,
                )
            )
        remaining = max(limit - len(sources), 0)
        if remaining <= 0:
            return sources
        for todo in active_project_todos[:remaining]:
            snippet_parts = [part for part in [todo.description or None, self._todo_timing_label(todo)] if part]
            sources.append(
                InsightSourceItem(
                    type="todo",
                    id=str(todo.id),
                    title=todo.title or "\u672a\u547d\u540d\u4efb\u52a1",
                    snippet=" \u00b7 ".join(snippet_parts)[:200] if snippet_parts else "\u4e0e\u9879\u76ee\u76f8\u5173\u7684\u5f85\u529e\u4efb\u52a1",
                    event_time=todo.due_at or todo.created_at,
                )
            )
        return sources

    def _project_focus(
        self,
        topic_counter: Counter[str],
        recent_projects: list[MemoryItem],
        active_project_todos: list[TodoItem],
    ) -> str:
        ignored = {"project", "todo", "memo", "\u9879\u76ee", "\u63a8\u8fdb"}
        for token, _count in topic_counter.most_common():
            normalized = token.strip()
            if normalized and normalized.lower() not in ignored and normalized not in ignored:
                return normalized
        if recent_projects:
            return recent_projects[0].title or "\u9879\u76ee\u63a8\u8fdb"
        if active_project_todos:
            return active_project_todos[0].title or "\u9879\u76ee\u63a8\u8fdb"
        return "\u9879\u76ee\u63a8\u8fdb"

    def _is_project_todo(self, todo: TodoItem) -> bool:
        haystack = f"{todo.title} {todo.description or ''}".lower()
        markers = [
            "project",
            "demo",
            "paper",
            "langgraph",
            "roomos",
            "rag",
            "\u9879\u76ee",
            "\u8bba\u6587",
            "\u6f14\u793a",
            "\u67b6\u6784",
        ]
        return any(marker in haystack for marker in markers)

    def _todo_timing_label(self, todo: TodoItem) -> str | None:
        due_at = ensure_utc(todo.due_at)
        if due_at is None:
            return None
        return f"\u622a\u6b62\u4e8e {due_at.isoformat()}"

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

    def _category_label(self, category: str) -> str:
        return {
            "electronics": "\u6570\u7801/\u7535\u5b50",
            "food": "\u9910\u996e",
            "transport": "\u4ea4\u901a",
            "housing": "\u5c45\u4f4f",
            "learning": "\u5b66\u4e60",
            "other": "\u5176\u4ed6",
        }.get(category, category)


dashboard_service = DashboardService()
