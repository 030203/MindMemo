import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.memory import MemoryItem
from app.models.review import ReviewQueueItem
from app.models.timeline import TimelineEvent
from app.models.todo import TodoItem
from app.repos.memory_repo import memory_repository
from app.repos.review_repo import review_repository
from app.repos.timeline_repo import timeline_repository
from app.repos.todo_repo import todo_repository
from app.schemas.review import ReviewQueueItemResponse



def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ReviewService:
    def list_reviews(self, db: Session, user_id: uuid.UUID) -> list[ReviewQueueItemResponse]:
        items = review_repository.list_for_user(db, user_id)
        return [self._to_response(db, item) for item in items]

    def confirm_review(
        self,
        db: Session,
        user_id: uuid.UUID,
        review_id: str,
        note: str = "",
    ) -> ReviewQueueItemResponse | None:
        item = review_repository.get_for_user(db, user_id, uuid.UUID(review_id))
        if item is None:
            return None

        item.status = "confirmed"
        item.user_decision = {"action": "confirm", "note": note}
        review_repository.save(db, item)
        self._add_review_timeline(db, item, "确认待处理项", note)
        db.commit()
        return self._to_response(db, item)

    def ignore_review(
        self,
        db: Session,
        user_id: uuid.UUID,
        review_id: str,
        note: str = "",
    ) -> ReviewQueueItemResponse | None:
        item = review_repository.get_for_user(db, user_id, uuid.UUID(review_id))
        if item is None:
            return None

        item.status = "rejected"
        item.user_decision = {"action": "ignore", "note": note}
        review_repository.save(db, item)
        self._add_review_timeline(db, item, "忽略待处理项", note)
        db.commit()
        return self._to_response(db, item)

    def convert_to_todo(
        self,
        db: Session,
        user_id: uuid.UUID,
        review_id: str,
        note: str = "",
    ) -> ReviewQueueItemResponse | None:
        item = review_repository.get_for_user(db, user_id, uuid.UUID(review_id))
        if item is None:
            return None

        memory = None
        if item.target_type == "memory":
            memory = memory_repository.get_for_user(db, user_id, item.target_id)

        title = self._resolve_target_title(db, user_id, item.target_type, item.target_id)
        description = note or item.reason or ""
        if memory is not None and memory.content_summary:
            description = f"{description}\n\n来源记录：{memory.content_summary}".strip()

        todo = TodoItem(
            user_id=user_id,
            source_memory_id=memory.id if memory is not None else None,
            title=title,
            description=description,
            status="pending",
            priority="medium",
            due_at=memory.due_time if memory is not None else None,
            risk_level="medium",
            meta_payload={"source": "review_queue", "review_id": str(item.id)},
        )
        todo_repository.create(db, todo)

        item.status = "confirmed"
        item.user_decision = {"action": "convert_to_todo", "note": note, "todo_id": str(todo.id)}
        review_repository.save(db, item)
        timeline_repository.create(
            db,
            TimelineEvent(
                user_id=user_id,
                event_type="todo_created",
                ref_type="todo",
                ref_id=todo.id,
                title=f"从待确认项转成 TODO：{todo.title}",
                summary=todo.description or "待确认项已转入 TODO Center。",
                event_time=utcnow(),
            ),
        )
        db.commit()
        return self._to_response(db, item)

    def enqueue_for_memory(self, db: Session, memory: MemoryItem) -> int:
        created = 0
        for payload in self._build_memory_review_payloads(memory):
            existing = review_repository.get_pending_for_target(
                db,
                memory.user_id,
                review_type=payload["review_type"],
                target_type="memory",
                target_id=memory.id,
            )
            if existing is not None:
                continue

            review_repository.create(
                db,
                ReviewQueueItem(
                    user_id=memory.user_id,
                    review_type=payload["review_type"],
                    target_type="memory",
                    target_id=memory.id,
                    suggestion=payload["suggestion"],
                    status="pending",
                    reason=payload["reason"],
                ),
            )
            created += 1
        return created

    def sync_all_users(self, db: Session) -> int:
        created = 0
        for memory in memory_repository.list_all_active(db):
            created += self.enqueue_for_memory(db, memory)
        if created > 0:
            db.commit()
        else:
            db.flush()
        return created

    def _resolve_target_title(self, db: Session, user_id: uuid.UUID, target_type: str, target_id) -> str:
        if target_type == "memory":
            memory = memory_repository.get_for_user(db, user_id, target_id)
            if memory is not None and memory.title:
                return memory.title
        return "待确认对象"

    def _to_response(self, db: Session, item: ReviewQueueItem) -> ReviewQueueItemResponse:
        return ReviewQueueItemResponse(
            id=str(item.id),
            review_type=item.review_type,
            reason=item.reason or "",
            target_title=self._resolve_target_title(db, item.user_id, item.target_type, item.target_id),
            status=item.status,
        )

    def _add_review_timeline(self, db: Session, item: ReviewQueueItem, title: str, note: str) -> None:
        timeline_repository.create(
            db,
            TimelineEvent(
                user_id=item.user_id,
                event_type="review_updated",
                ref_type=item.target_type,
                ref_id=item.target_id,
                title=f"{title}：{self._resolve_target_title(db, item.user_id, item.target_type, item.target_id)}",
                summary=note or item.reason or "",
                event_time=utcnow(),
            ),
        )

    def _build_memory_review_payloads(self, memory: MemoryItem) -> list[dict]:
        payloads: list[dict] = []
        suggestion = {
            "category": memory.category,
            "tags": list(memory.tags or []),
        }

        if memory.category == "project":
            payloads.append(
                {
                    "review_type": "relation_confirmation",
                    "suggestion": suggestion,
                    "reason": "项目类记录通常会影响后续回顾和问答，建议确认它是否应该关联到现有项目。",
                }
            )

        if memory.is_todo_candidate:
            payloads.append(
                {
                    "review_type": "todo_approval",
                    "suggestion": suggestion,
                    "reason": "这条记录看起来像一个待办事项，需要你确认后再转成 TODO。",
                }
            )

        return payloads


review_service = ReviewService()
