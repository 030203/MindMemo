from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.chat import ChatSession
from app.repos.chat_repo import chat_repository
from app.repos.memory_repo import memory_repository
from app.repos.todo_repo import todo_repository


class ChatService:
    HISTORY_WINDOW = 20

    # ------------------------------------------------------------------
    # Session 管理
    # ------------------------------------------------------------------
    def get_or_create_session(
        self,
        db: Session,
        user_id: uuid.UUID,
        context_type: str,
        context_id: str | None,
        title: str | None,
    ) -> ChatSession:
        existing = chat_repository.find_active(db, user_id, context_type, context_id)
        if existing is not None:
            return existing
        return chat_repository.create_session(db, user_id, context_type, context_id, title)

    def get_session_for_user(
        self, db: Session, user_id: uuid.UUID, session_id: str
    ) -> ChatSession | None:
        return chat_repository.get_session(db, user_id, session_id)

    # ------------------------------------------------------------------
    # 消息
    # ------------------------------------------------------------------
    def get_history_window(self, db: Session, session_id: str) -> list[dict]:
        messages = chat_repository.list_messages(db, session_id, limit=self.HISTORY_WINDOW)
        return [{"role": m.role, "content": m.content} for m in messages]

    def append_exchange(self, db: Session, session_id: str, question: str, answer: str):
        chat_repository.add_message(db, session_id, role="user", content=question)
        msg = chat_repository.add_message(db, session_id, role="assistant", content=answer)
        return msg

    # ------------------------------------------------------------------
    # 上下文构建
    # ------------------------------------------------------------------
    def build_context_doc(
        self, db: Session, user_id: uuid.UUID, context_type: str, context_id: str | None
    ) -> str | None:
        if not context_id:
            return None
        try:
            cid = uuid.UUID(context_id)
        except ValueError:
            return None

        if context_type == "memory":
            mem = memory_repository.get_for_user(db, user_id, cid)
            if mem is None:
                return None
            return f"标题：{mem.title or ''}\n\n{mem.content_raw or ''}"

        if context_type == "todo":
            todo = todo_repository.get_for_user(db, user_id, cid)
            if todo is None:
                return None
            parts = [f"待办标题：{todo.title}"]
            if todo.description:
                parts.append(f"描述：{todo.description}")
            if todo.due_at:
                parts.append(f"截止时间：{todo.due_at.isoformat()}")
            return "\n".join(parts)

        return None

    def build_global_context(
        self, db: Session, user_id: uuid.UUID, question: str, max_items: int = 5,
    ) -> str | None:
        """为全局会话做轻量记忆检索，拼成上下文文档。

        用 ILIKE 在 title/content_summary/content_raw 中搜关键词，
        取最近 max_items 条，拼成可供 chat_stream 消费的 context_doc。
        """
        try:
            memories = memory_repository.list_for_user(
                db, user_id, query_text=question,
            )
        except Exception:
            return None

        if not memories:
            # 关键词没命中，退回到最近记录
            try:
                memories = memory_repository.list_for_user(db, user_id)[:max_items]
            except Exception:
                return None

        if not memories:
            return None

        parts: list[str] = []
        for mem in memories[:max_items]:
            title = mem.title or "未命名"
            content = (mem.content_raw or "")[:2000]  # 限制每条长度
            parts.append(f"【{title}】\n{content}")

        return "\n\n---\n\n".join(parts)

    def auto_title_if_needed(self, db: Session, session_id: str, question: str) -> None:
        """第一次对话后，自动用问题前 20 字当会话标题。"""
        try:
            from sqlalchemy import select
            from app.models.chat import ChatSession
            stmt = select(ChatSession).where(ChatSession.id == session_id)
            s = db.execute(stmt).scalar_one_or_none()
            if s and not s.title:
                title = question.strip().replace("\n", " ")
                s.title = title[:20] + ("..." if len(title) > 20 else "")
                db.flush()
        except Exception:
            pass

    def list_sessions(
        self, db: Session, user_id: uuid.UUID,
    ) -> list[ChatSession]:
        """列出用户的所有活跃会话（按更新时间倒序）"""
        from sqlalchemy import desc, select
        stmt = (
            select(ChatSession)
            .where(ChatSession.user_id == user_id, ChatSession.deleted_at.is_(None))
            .order_by(ChatSession.pinned.desc(), desc(ChatSession.updated_at))
        )
        return list(db.execute(stmt).scalars().all())


chat_service = ChatService()
