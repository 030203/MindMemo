import uuid

from sqlalchemy import cast, delete, desc, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.memory import MemoryChunk
from pgvector.sqlalchemy import Vector


class MemoryChunkRepository:
    def list_all(self, db: Session) -> list[MemoryChunk]:
        stmt = select(MemoryChunk).order_by(MemoryChunk.created_at.asc(), MemoryChunk.chunk_index.asc())
        return list(db.execute(stmt).scalars().all())

    def list_for_user(self, db: Session, user_id: uuid.UUID) -> list[MemoryChunk]:
        stmt = (
            select(MemoryChunk)
            .where(MemoryChunk.user_id == user_id)
            .order_by(desc(MemoryChunk.created_at), MemoryChunk.chunk_index.asc())
        )
        return list(db.execute(stmt).scalars().all())

    def list_for_memory(self, db: Session, memory_id: uuid.UUID) -> list[MemoryChunk]:
        stmt = (
            select(MemoryChunk)
            .where(MemoryChunk.memory_id == memory_id)
            .order_by(MemoryChunk.chunk_index.asc())
        )
        return list(db.execute(stmt).scalars().all())

    def count_for_memory(self, db: Session, memory_id: uuid.UUID) -> int:
        stmt = select(MemoryChunk).where(MemoryChunk.memory_id == memory_id)
        return len(db.execute(stmt).scalars().all())

    def list_missing_embeddings(self, db: Session) -> list[MemoryChunk]:
        stmt = select(MemoryChunk).where(MemoryChunk.embedding.is_(None)).order_by(MemoryChunk.created_at.asc())
        return list(db.execute(stmt).scalars().all())

    def search_similar_chunks(
        self,
        db: Session,
        user_id: uuid.UUID,
        query_embedding: list[float],
        *,
        limit: int = 12,
        memory_ids: list[uuid.UUID] | None = None,
    ) -> list[tuple[MemoryChunk, float]]:
        if db.bind is None or db.bind.dialect.name != "postgresql":
            return []

        vector_column = cast(MemoryChunk.embedding, Vector(settings.embedding_dimension))
        similarity = (1 - vector_column.cosine_distance(query_embedding)).label("similarity")
        stmt = (
            select(MemoryChunk, similarity)
            .where(MemoryChunk.user_id == user_id, MemoryChunk.embedding.is_not(None))
            .order_by(vector_column.cosine_distance(query_embedding))
            .limit(limit)
        )
        if memory_ids:
            stmt = stmt.where(MemoryChunk.memory_id.in_(memory_ids))
        rows = db.execute(stmt).all()
        return [(row[0], float(row[1])) for row in rows]

    def replace_for_memory(self, db: Session, memory_id: uuid.UUID, chunks: list[MemoryChunk]) -> list[MemoryChunk]:
        db.execute(delete(MemoryChunk).where(MemoryChunk.memory_id == memory_id))
        for chunk in chunks:
            db.add(chunk)
        db.flush()
        return chunks


memory_chunk_repository = MemoryChunkRepository()
