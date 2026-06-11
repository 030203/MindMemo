from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.memory import MemoryItem
from app.models.timeline import TimelineEvent
from app.models.todo import TodoItem
from app.repos.fact_repo import fact_repository
from app.repos.memory_repo import memory_repository
from app.repos.reminder_repo import reminder_repository
from app.repos.timeline_repo import timeline_repository
from app.repos.todo_repo import todo_repository
from app.schemas.memory import ExtractedFactResponse, MemoryCreateRequest, MemoryDetail, MemoryListItem, MemoryUpdateRequest
from app.services.chunk_service import chunk_service
from app.services.dashboard_service import dashboard_service
from app.services.fact_extraction_service import fact_extraction_service
from app.services.memory_relation_service import memory_relation_service
from app.services.memory_understanding_service import memory_understanding_service
from app.services.reminder_service import reminder_service
from app.services.review_service import review_service


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _derive_tags(content: str, category: str) -> list[str]:
    base_tags = {
        "learning": ["学习", "知识"],
        "project": ["项目", "推进"],
        "idea": ["灵感", "想法"],
        "memo": ["备忘", "记录"],
    }.get(category, ["记录"])
    keywords = [word for word in ["LangGraph", "Agent", "论文", "任务", "提醒"] if word in content]
    return list(dict.fromkeys(base_tags + keywords))


def _summarize(content: str) -> str:
    compact = content.strip().replace("\n", " ")
    return compact if len(compact) <= 68 else f"{compact[:68].rstrip()}..."


def _to_memory_list_item(memory: MemoryItem) -> MemoryListItem:
    source_meta = memory.time_info or {}
    return MemoryListItem(
        id=str(memory.id),
        title=memory.title or "Untitled Memory",
        source_type=memory.source_type,
        source_url=source_meta.get("source_url"),
        file_name=source_meta.get("file_name"),
        content_summary=memory.content_summary or "",
        category=memory.category,
        tags=list(memory.tags or []),
        importance_score=float(memory.importance_score),
        event_time=memory.event_time,
        due_time=memory.due_time,
        status=memory.status,
    )


def _to_fact_response(fact) -> ExtractedFactResponse:
    return ExtractedFactResponse(
        id=str(fact.id),
        fact_type=fact.fact_type,
        title=fact.title,
        structured_payload=dict(fact.structured_payload or {}),
        confidence_score=float(fact.confidence_score),
        event_time=fact.event_time,
        source=fact.source,
    )


def _to_memory_detail(memory: MemoryItem, facts=None) -> MemoryDetail:
    return MemoryDetail(
        **_to_memory_list_item(memory).model_dump(),
        content_raw=memory.content_raw,
        keywords=list(memory.keywords or []),
        entities=list(memory.entities or []),
        extracted_facts=[_to_fact_response(fact) for fact in (facts or [])],
    )


class MemoryService:
    def list_memories(
        self,
        db: Session,
        user_id: uuid.UUID,
        query_text: str | None = None,
        category: str | None = None,
    ) -> list[MemoryListItem]:
        memories = memory_repository.list_for_user(db, user_id, query_text=query_text, category=category)
        return [_to_memory_list_item(memory) for memory in memories]

    def get_memory(self, db: Session, user_id: uuid.UUID, memory_id: str) -> MemoryDetail | None:
        memory = memory_repository.get_for_user(db, user_id, uuid.UUID(memory_id))
        if memory is None:
            return None
        facts = fact_repository.list_for_memory(db, user_id, memory.id)
        return _to_memory_detail(memory, facts)

    def get_memory_model(self, db: Session, user_id: uuid.UUID, memory_id: str) -> MemoryItem | None:
        return memory_repository.get_for_user(db, user_id, uuid.UUID(memory_id))

    def create_memory(self, db: Session, user_id: uuid.UUID, payload: MemoryCreateRequest) -> MemoryDetail:
        time_info = {}
        if payload.source_url:
            time_info["source_url"] = payload.source_url
        if payload.file_name:
            time_info["file_name"] = payload.file_name
        if payload.source_mime_type:
            time_info["source_mime_type"] = payload.source_mime_type

        return self._create_memory_record(
            db,
            user_id,
            title=payload.title,
            content=payload.content,
            category=payload.category,
            source_type=payload.source_type,
            time_info=time_info,
            timeline_title=f"记录了一条内容：{payload.title.strip() or '未命名记录'}",
        )

    def create_ingested_memory(
        self,
        db: Session,
        user_id: uuid.UUID,
        *,
        title: str,
        content: str,
        category: str,
        source_type: str,
        time_info: dict,
    ) -> MemoryDetail:
        source_label = {
            "url": "导入网页",
            "pdf": "导入 PDF",
            "image": "保存截图",
        }.get(source_type, "导入内容")
        return self._create_memory_record(
            db,
            user_id,
            title=title,
            content=content,
            category=category,
            source_type=source_type,
            time_info=time_info,
            timeline_title=f"{source_label}：{title.strip() or '未命名记录'}",
        )

    def sync_memory_todos(self, db: Session, user_id: uuid.UUID | None = None) -> int:
        synced = 0
        for memory in memory_repository.list_all_active(db):
            if user_id is not None and memory.user_id != user_id:
                continue
            content = (memory.content_clean or memory.content_raw or "").strip()
            if not content:
                continue

            plan_metadata = fact_extraction_service.extract_plan_metadata(content, memory.event_time or memory.created_at)
            if not plan_metadata["is_todo_candidate"]:
                archived = self._archive_auto_todo_for_memory(db, memory)
                if memory.is_todo_candidate:
                    memory.is_todo_candidate = False
                    memory.due_time = None
                    synced += 1
                else:
                    synced += archived
                continue

            memory.is_todo_candidate = True
            memory.due_time = plan_metadata["due_time"]
            self._sync_todo_for_memory(db, memory)
            synced += 1

        if synced > 0:
            db.commit()
            dashboard_service.invalidate_insight_cache(user_id)
        else:
            db.flush()
        return synced

    def update_memory(
        self,
        db: Session,
        user_id: uuid.UUID,
        memory_id: str,
        payload: MemoryUpdateRequest,
    ) -> MemoryDetail | None:
        memory = memory_repository.get_for_user(db, user_id, uuid.UUID(memory_id))
        if memory is None:
            return None

        normalized_content = payload.content.strip()
        understanding = memory_understanding_service.understand(normalized_content, payload.category)
        plan_metadata = fact_extraction_service.extract_plan_metadata(normalized_content, memory.event_time or utcnow())

        memory.title = payload.title.strip() or memory.title
        memory.content_raw = payload.content
        memory.content_clean = normalized_content
        memory.content_summary = _summarize(payload.content)
        memory.category = payload.category
        memory.tags = understanding.tags
        memory.keywords = understanding.keywords
        memory.entities = understanding.entities
        memory.is_todo_candidate = plan_metadata["is_todo_candidate"]
        memory.due_time = plan_metadata["due_time"]

        chunk_service.rebuild_chunks_for_memory(db, memory)
        fact_extraction_service.rebuild_facts_for_memory(db, memory)
        memory_relation_service.rebuild_for_memory(db, user_id, memory)
        self._sync_todo_for_memory(db, memory)
        timeline_repository.create(
            db,
            TimelineEvent(
                user_id=user_id,
                event_type="memory_created",
                ref_type="memory",
                ref_id=memory.id,
                title=f"更新了记录：{memory.title}",
                summary=memory.content_summary or "",
                event_time=utcnow(),
            ),
        )

        db.commit()
        dashboard_service.invalidate_insight_cache(user_id)
        db.refresh(memory)
        facts = fact_repository.list_for_memory(db, user_id, memory.id)
        return _to_memory_detail(memory, facts)

    def delete_memory(self, db: Session, user_id: uuid.UUID, memory_id: str) -> bool:
        memory = memory_repository.get_for_user(db, user_id, uuid.UUID(memory_id))
        if memory is None:
            return False

        now = utcnow()
        memory.deleted_at = now
        memory.status = "deleted"
        self._archive_auto_todo_for_memory(db, memory)
        timeline_repository.create(
            db,
            TimelineEvent(
                user_id=user_id,
                event_type="memory_deleted",
                ref_type="memory",
                ref_id=memory.id,
                title=f"删除了记录：{memory.title or '未命名记录'}",
                summary=memory.content_summary or "",
                event_time=now,
            ),
        )

        db.commit()
        dashboard_service.invalidate_insight_cache(user_id)
        return True

    def _create_memory_record(
        self,
        db: Session,
        user_id: uuid.UUID,
        *,
        title: str,
        content: str,
        category: str,
        source_type: str,
        time_info: dict,
        timeline_title: str,
    ) -> MemoryDetail:
        normalized_title = title.strip() or "Untitled Memory"
        normalized_content = content.strip()
        understanding = memory_understanding_service.understand(normalized_content, category)
        now = utcnow()
        plan_metadata = fact_extraction_service.extract_plan_metadata(normalized_content, now)

        memory = MemoryItem(
            user_id=user_id,
            source_type=source_type,
            title=normalized_title,
            content_raw=content,
            content_clean=normalized_content,
            content_summary=_summarize(content),
            category=category,
            tags=understanding.tags,
            keywords=understanding.keywords,
            entities=understanding.entities,
            time_info=time_info,
            importance_score=0.76,
            confidence_score=0.82,
            status="active",
            is_todo_candidate=plan_metadata["is_todo_candidate"],
            event_time=now,
            due_time=plan_metadata["due_time"],
            created_by="user",
        )
        memory_repository.create(db, memory)
        chunk_service.rebuild_chunks_for_memory(db, memory)
        fact_extraction_service.rebuild_facts_for_memory(db, memory)
        memory_relation_service.rebuild_for_memory(db, user_id, memory)
        timeline_repository.create(
            db,
            TimelineEvent(
                user_id=user_id,
                event_type="memory_created",
                ref_type="memory",
                ref_id=memory.id,
                title=timeline_title,
                summary=memory.content_summary or "",
                event_time=utcnow(),
            ),
        )

        review_service.enqueue_for_memory(db, memory)
        self._sync_todo_for_memory(db, memory)

        db.commit()
        dashboard_service.invalidate_insight_cache(user_id)
        db.refresh(memory)
        facts = fact_repository.list_for_memory(db, user_id, memory.id)
        return _to_memory_detail(memory, facts)

    def _sync_todo_for_memory(self, db: Session, memory: MemoryItem) -> TodoItem | None:
        existing = todo_repository.get_for_source_memory(db, memory.user_id, memory.id)
        if not memory.is_todo_candidate:
            self._archive_auto_todo_for_memory(db, memory)
            return existing

        title = memory.title or _summarize(memory.content_raw)
        description = f"来源记录：{memory.content_summary or memory.content_raw}".strip()
        if existing is None:
            todo = TodoItem(
                user_id=memory.user_id,
                source_memory_id=memory.id,
                title=title,
                description=description,
                status="pending",
                priority="medium",
                due_at=memory.due_time,
                risk_level="medium" if memory.due_time is not None else "low",
                ai_generated=True,
                requires_approval=False,
                meta_payload={"source": "memory_auto_parse"},
            )
            todo_repository.create(db, todo)
            timeline_repository.create(
                db,
                TimelineEvent(
                    user_id=memory.user_id,
                    event_type="todo_created",
                    ref_type="todo",
                    ref_id=todo.id,
                    title=f"从记录自动生成待办：{todo.title}",
                    summary=todo.description or "这条记录包含提醒或待办线索。",
                    event_time=utcnow(),
                ),
            )
        else:
            todo = existing
            todo.title = title
            todo.description = description
            todo.due_at = memory.due_time
            todo.risk_level = "medium" if memory.due_time is not None else todo.risk_level

        reminder_service.sync_user_reminders(db, memory.user_id)
        return todo

    def _archive_auto_todo_for_memory(self, db: Session, memory: MemoryItem) -> int:
        existing = todo_repository.get_for_source_memory(db, memory.user_id, memory.id)
        if existing is None:
            return 0

        meta_payload = existing.meta_payload or {}
        if not existing.ai_generated or meta_payload.get("source") != "memory_auto_parse":
            return 0

        existing.deleted_at = existing.deleted_at or utcnow()
        for reminder in reminder_repository.list_for_todo(db, existing.id):
            if reminder.status == "active":
                reminder.status = "dismissed"
        return 1


memory_service = MemoryService()
