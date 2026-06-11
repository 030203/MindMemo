from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.security import hash_password
from app.models import Base
from app.models.memory import MemoryItem
from app.models.review import ReviewQueueItem
from app.models.timeline import TimelineEvent
from app.models.todo import TodoItem
from app.repos.user_repo import user_repository
from app.services.chunk_service import chunk_service
from app.services.memory_relation_service import memory_relation_service
from app.services.memory_service import memory_service
from app.services.reminder_service import reminder_service
from app.services.review_service import review_service

DEMO_USER_EMAIL = "demo@example.com"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def initialize_database() -> None:
    if settings.database_url.startswith("sqlite"):
        Path("data").mkdir(parents=True, exist_ok=True)

    ensure_postgres_vector_extension()
    Base.metadata.create_all(bind=engine)
    ensure_postgres_vector_indexes()
    apply_local_schema_fixes()

    with SessionLocal() as db:
        ensure_demo_user(db)
        seed_demo_data(db)
        backfill_chunks(db)
        refresh_chunk_embeddings(db)
        backfill_memory_relations(db)
        memory_service.sync_memory_todos(db)
        review_service.sync_all_users(db)
        reminder_service.sync_all_users(db)


def apply_local_schema_fixes() -> None:
    with engine.begin() as conn:
        if settings.database_url.startswith("sqlite"):
            user_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()]
            if "last_login_at" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN last_login_at DATETIME"))
            agent_run_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(agent_runs)")).fetchall()]
            if agent_run_columns and "error_message" not in agent_run_columns:
                conn.execute(text("ALTER TABLE agent_runs ADD COLUMN error_message TEXT"))
            agent_run_step_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(agent_run_steps)")).fetchall()]
            if agent_run_step_columns and "error_message" not in agent_run_step_columns:
                conn.execute(text("ALTER TABLE agent_run_steps ADD COLUMN error_message TEXT"))
            return

        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS reminder_events (
                    id UUID PRIMARY KEY,
                    user_id UUID NOT NULL REFERENCES users(id),
                    todo_id UUID NOT NULL REFERENCES todos(id),
                    reminder_type VARCHAR(32) NOT NULL,
                    level VARCHAR(16) NOT NULL,
                    title VARCHAR(255) NOT NULL,
                    message TEXT NOT NULL,
                    due_at TIMESTAMP NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    sent_at TIMESTAMP NULL,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reminder_events_user_id ON reminder_events (user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_reminder_events_todo_id ON reminder_events (todo_id)"))
        conn.execute(text("ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS error_message TEXT"))
        conn.execute(text("ALTER TABLE agent_run_steps ADD COLUMN IF NOT EXISTS error_message TEXT"))


def ensure_postgres_vector_extension() -> None:
    if not settings.database_url.startswith("postgresql"):
        return

    with engine.begin() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "PostgreSQL is configured, but pgvector extension could not be initialized."
            ) from exc


def ensure_postgres_vector_indexes() -> None:
    if not settings.database_url.startswith("postgresql"):
        return

    with engine.begin() as conn:
        try:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_memory_chunks_embedding_hnsw "
                    "ON memory_chunks USING hnsw (embedding vector_cosine_ops)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_memory_chunks_user_created "
                    "ON memory_chunks (user_id, created_at DESC)"
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "PostgreSQL is configured, but pgvector indexes could not be initialized."
            ) from exc


def ensure_demo_user(db: Session):
    user = user_repository.get_by_email(db, DEMO_USER_EMAIL)
    if user is not None:
        if not user.password_hash.startswith("pbkdf2_sha256$"):
            user.password_hash = hash_password("demo123456")
            db.commit()
            db.refresh(user)
        return user

    user = user_repository.create_user(
        db,
        email=DEMO_USER_EMAIL,
        password_hash=hash_password("demo123456"),
        display_name="Demo User",
    )
    user_repository.create_settings(db, user.id)
    db.commit()
    db.refresh(user)
    return user


def seed_demo_data(db: Session) -> None:
    user = ensure_demo_user(db)

    has_existing_memory = (
        db.query(MemoryItem).filter(MemoryItem.user_id == user.id, MemoryItem.deleted_at.is_(None)).first()
    )
    if has_existing_memory is not None:
        return

    now = utcnow()

    memory_1 = MemoryItem(
        user_id=user.id,
        source_type="memo",
        title="LangGraph 学习记录",
        content_raw="今天学习了 state graph、conditional edge，以及为什么多 Agent 需要明确状态边界。",
        content_clean="今天学习了 state graph、conditional edge，以及为什么多 Agent 需要明确状态边界。",
        content_summary="记录了 LangGraph 的状态图、条件边和多 Agent 编排要点。",
        category="learning",
        tags=["LangGraph", "Agent", "Workflow"],
        keywords=["state graph", "conditional edge", "workflow"],
        entities=["LangGraph", "StateGraph"],
        time_info={},
        importance_score=0.92,
        confidence_score=0.91,
        event_time=now - timedelta(days=1),
        created_by="user",
    )
    db.add(memory_1)
    db.flush()

    memory_2 = MemoryItem(
        user_id=user.id,
        source_type="memo",
        title="论文初稿计划",
        content_raw="本周内需要完成论文初稿提纲，周三前出目录，周五前完成首版。",
        content_clean="本周内需要完成论文初稿提纲，周三前出目录，周五前完成首版。",
        content_summary="需要在本周推进论文初稿，包含周三目录和周五首版两个关键节点。",
        category="project",
        tags=["论文", "计划"],
        keywords=["初稿", "目录", "周五"],
        entities=["论文初稿"],
        time_info={},
        importance_score=0.88,
        confidence_score=0.73,
        due_time=now + timedelta(days=2),
        event_time=now - timedelta(days=2),
        created_by="user",
    )
    db.add(memory_2)
    db.flush()

    todo_1 = TodoItem(
        user_id=user.id,
        title="完成 LangGraph Demo",
        description="搭建一个 memory ingest workflow 示例",
        status="doing",
        priority="high",
        due_at=now + timedelta(days=1),
        risk_level="medium",
    )
    todo_2 = TodoItem(
        user_id=user.id,
        title="整理面试题清单",
        description="总结项目亮点、RAG、Agent、长期记忆设计",
        status="pending",
        priority="medium",
        due_at=now + timedelta(days=3),
        risk_level="low",
    )
    db.add_all([todo_1, todo_2])
    db.flush()

    db.add_all(
        [
            TimelineEvent(
                user_id=user.id,
                event_type="memory_created",
                ref_type="memory",
                ref_id=memory_1.id,
                title="记录了 LangGraph 学习笔记",
                summary="新增一条学习类记忆，包含 workflow 和状态图要点。",
                event_time=now - timedelta(days=1, hours=2),
            ),
            TimelineEvent(
                user_id=user.id,
                event_type="todo_created",
                ref_type="todo",
                ref_id=todo_1.id,
                title="创建任务：完成 LangGraph Demo",
                summary="一条高优先级任务进入 TODO Center。",
                event_time=now - timedelta(hours=10),
            ),
            ReviewQueueItem(
                user_id=user.id,
                review_type="low_confidence",
                target_type="memory",
                target_id=memory_2.id,
                ai_suggestion={"category": "project", "tags": ["论文", "计划"]},
                status="pending",
                reason="系统识别到这条记录可能同时属于 Learning 和 Project，需要你确认分类。",
            ),
        ]
    )

    db.commit()


def backfill_chunks(db: Session) -> None:
    memories = db.query(MemoryItem).filter(MemoryItem.deleted_at.is_(None)).all()
    rebuilt = chunk_service.backfill_missing_chunks(db, memories)
    if rebuilt > 0:
        db.commit()


def refresh_chunk_embeddings(db: Session) -> None:
    filled = chunk_service.refresh_chunk_embeddings(db)
    if filled > 0:
        db.commit()


def backfill_memory_relations(db: Session) -> None:
    from app.repos.memory_relation_repo import memory_relation_repository

    if memory_relation_repository.count_all(db) > 0:
        return
    rebuilt = memory_relation_service.backfill_all_users(db)
    if rebuilt > 0:
        db.commit()
