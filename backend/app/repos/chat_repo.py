import uuid

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.chat import ChatMessage, ChatSession


class ChatRepository:
    def get_session(
        self, db: Session, user_id: uuid.UUID, session_id: str
    ) -> ChatSession | None:
        stmt = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user_id,
            ChatSession.deleted_at.is_(None),
        )
        return db.execute(stmt).scalar_one_or_none()

    def find_active(
        self, db: Session, user_id: uuid.UUID, context_type: str, context_id: str | None
    ) -> ChatSession | None:
        stmt = select(ChatSession).where(
            ChatSession.user_id == user_id,
            ChatSession.context_type == context_type,
            ChatSession.deleted_at.is_(None),
        )
        if context_id is None:
            stmt = stmt.where(ChatSession.context_id.is_(None))
        else:
            stmt = stmt.where(ChatSession.context_id == context_id)
        stmt = stmt.order_by(desc(ChatSession.updated_at)).limit(1)
        return db.execute(stmt).scalar_one_or_none()

    def create_session(
        self, db: Session, user_id: uuid.UUID, context_type: str,
        context_id: str | None, title: str | None,
    ) -> ChatSession:
        session = ChatSession(
            user_id=user_id,
            context_type=context_type,
            context_id=context_id,
            title=title,
        )
        db.add(session)
        db.flush()
        db.refresh(session)
        return session

    def list_messages(
        self, db: Session, session_id: str, limit: int = 20
    ) -> list[ChatMessage]:
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at)
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())

    def add_message(
        self, db: Session, session_id: str, role: str, content: str
    ) -> ChatMessage:
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
        )
        db.add(msg)
        db.flush()
        db.refresh(msg)
        return msg

    def soft_delete(self, db: Session, session: ChatSession) -> None:
        from app.models.base import utcnow
        session.deleted_at = utcnow()
        db.flush()


chat_repository = ChatRepository()
