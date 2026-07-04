from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.memory import MemoryItem
from app.models.timeline import TimelineEvent
from app.repos.memory_repo import memory_repository
from app.repos.timeline_repo import timeline_repository
from app.schemas.memory import MemoryCreateRequest, MemoryDetail, MemoryListItem, MemoryUpdateRequest
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


def _to_memory_detail(memory: MemoryItem) -> MemoryDetail:
    return MemoryDetail(
        **_to_memory_list_item(memory).model_dump(),
        content_raw=memory.content_raw,
        keywords=list(memory.keywords or []),
        entities=list(memory.entities or []),
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
        return _to_memory_detail(memory)

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

        memory.title = payload.title.strip() or memory.title
        memory.content_raw = payload.content
        memory.content_clean = normalized_content
        memory.content_summary = _summarize(payload.content)
        memory.category = payload.category
        memory.tags = _derive_tags(normalized_content, payload.category)

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
        db.refresh(memory)
        return _to_memory_detail(memory)

    def delete_memory(self, db: Session, user_id: uuid.UUID, memory_id: str) -> bool:
        memory = memory_repository.get_for_user(db, user_id, uuid.UUID(memory_id))
        if memory is None:
            return False

        now = utcnow()
        memory.deleted_at = now
        memory.status = "deleted"
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
        now = utcnow()

        memory = MemoryItem(
            user_id=user_id,
            source_type=source_type,
            title=normalized_title,
            content_raw=content,
            content_clean=normalized_content,
            content_summary=_summarize(content),
            category=category,
            tags=_derive_tags(normalized_content, category),
            keywords=[],
            entities=[],
            time_info=time_info,
            importance_score=0.76,
            status="active",
            is_todo_candidate=False,
            event_time=now,
            due_time=None,
            created_by="user",
        )
        memory_repository.create(db, memory)
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

        db.commit()
        db.refresh(memory)
        return _to_memory_detail(memory)


memory_service = MemoryService()
