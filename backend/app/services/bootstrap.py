from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.models import Base
from app.services.reminder_service import reminder_service
from app.services.review_service import review_service


def utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def initialize_database() -> None:
    if settings.database_url.startswith("sqlite"):
        Path("data").mkdir(parents=True, exist_ok=True)

    Base.metadata.create_all(bind=engine)
    apply_local_schema_fixes()

    with SessionLocal() as db:
        review_service.sync_all_users(db)
        reminder_service.sync_all_users(db)


def initialize_tools() -> None:
    """注册 Phase 2 工具到全局 ToolRegistry + 注入到 qa_workflow。"""
    from app.tools.registry import get_global_registry
    from app.tools.retrieval.hybrid_search import HybridSearchTool
    from app.tools.retrieval.read_memory import ReadMemoryTool
    from app.tools.retrieval.list_tasks import ListTasksTool
    from app.tools.retrieval.time_resolver import TimeResolverTool
    from app.tools.retrieval.fact_extractor import FactExtractorTool
    from app.tools.memory.relation_finder import RelationFinderTool
    from app.tools.external.web_search import WebSearchTool
    from app.tools.external.weather import WeatherTool
    from app.orchestration.qa_workflow import qa_workflow
    from app.agent.react_agent import ReActAgent

    registry = get_global_registry()
    registry.register(HybridSearchTool)
    registry.register(ReadMemoryTool)
    registry.register(ListTasksTool)
    registry.register(TimeResolverTool)
    registry.register(FactExtractorTool)
    registry.register(RelationFinderTool)
    registry.register(WebSearchTool)
    registry.register(WeatherTool)

    # 注入到全局 qa_workflow
    qa_workflow._tool_registry = registry
    qa_workflow._react_agent = ReActAgent(tool_registry=registry)


def _run_safe(sql: str):
    """在独立事务中执行一条 DDL，失败不抛异常。"""
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
    except Exception:
        pass


def apply_local_schema_fixes() -> None:
    if settings.database_url.startswith("sqlite"):
        with engine.begin() as conn:
            user_columns = [row[1] for row in conn.execute(text("PRAGMA table_info(users)")).fetchall()]
            if "last_login_at" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN last_login_at DATETIME"))
            if "last_maintenance_at" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN last_maintenance_at DATETIME"))
        _run_safe("""
            CREATE TABLE IF NOT EXISTS agent_runs (
                id UUID PRIMARY KEY,
                user_id UUID NOT NULL,
                session_id VARCHAR(64) NOT NULL,
                agent_name VARCHAR(64) NOT NULL,
                question TEXT NOT NULL DEFAULT '',
                answer TEXT,
                trajectory JSON,
                tool_calls JSON,
                run_metadata JSON,
                duration_ms INTEGER,
                status VARCHAR(20) NOT NULL DEFAULT 'success',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
        """)
        _run_safe("CREATE INDEX IF NOT EXISTS ix_agent_runs_user_id ON agent_runs (user_id)")
        _run_safe("CREATE INDEX IF NOT EXISTS ix_agent_runs_session_id ON agent_runs (session_id)")
        return

    # ── PostgreSQL schema fixes ────────────────────────────────
    # Each DDL in its own transaction to avoid cascade failures

    _run_safe("""
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
    """)
    _run_safe("CREATE INDEX IF NOT EXISTS ix_reminder_events_user_id ON reminder_events (user_id)")
    _run_safe("CREATE INDEX IF NOT EXISTS ix_reminder_events_todo_id ON reminder_events (todo_id)")
    _run_safe("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_maintenance_at TIMESTAMP")
    _run_safe("DROP TABLE IF EXISTS agent_runs CASCADE")
    _run_safe("""
        CREATE TABLE agent_runs (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL,
            session_id VARCHAR(64) NOT NULL,
            agent_name VARCHAR(64) NOT NULL,
            question TEXT NOT NULL DEFAULT '',
            answer TEXT,
            trajectory JSONB,
            tool_calls JSONB,
            run_metadata JSONB,
            duration_ms INTEGER,
            status VARCHAR(20) NOT NULL DEFAULT 'success',
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL
        )
    """)
    _run_safe("CREATE INDEX IF NOT EXISTS ix_agent_runs_user_id ON agent_runs (user_id)")
    _run_safe("CREATE INDEX IF NOT EXISTS ix_agent_runs_session_id ON agent_runs (session_id)")
