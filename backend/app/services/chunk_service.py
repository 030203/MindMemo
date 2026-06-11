from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
import re
import uuid

from sqlalchemy.orm import Session

from app.models.memory import MemoryChunk, MemoryItem
from app.repos.memory_chunk_repo import memory_chunk_repository
from app.services.embedding_service import embedding_service
from app.services.query_router_service import query_router_service

SENTENCE_SPLIT_RE = re.compile(r"[\u3002\uff01\uff1f!?\uff1b;\n]+")
ALNUM_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}")
CHINESE_SEQ_RE = re.compile(r"[\u4e00-\u9fff]{2,}")

INTENT_KEYWORDS: dict[str, list[str]] = {
    "expense": [
        "\u82b1\u4e86",
        "\u6d88\u8d39",
        "\u5f00\u9500",
        "\u652f\u51fa",
        "\u4e70",
        "\u5143",
        "\u5496\u5561",
        "\u8033\u673a",
    ],
    "mood": [
        "\u7761\u5f97",
        "\u7761\u7720",
        "\u60c5\u7eea",
        "\u5fc3\u60c5",
        "\u75b2\u60eb",
        "\u7cbe\u795e",
        "\u7126\u8651",
        "\u538b\u529b",
    ],
    "plan": [
        "\u4e0b\u4e2a\u6708",
        "\u8bb0\u5f97",
        "\u63d0\u9192",
        "\u5f85\u529e",
        "\u8ba1\u5212",
        "\u5904\u7406",
        "\u623f\u79df",
    ],
    "learning": [
        "\u5b66\u4e60",
        "\u7814\u7a76",
        "\u6280\u672f",
        "\u67b6\u6784",
        "\u8bba\u6587",
        "rag",
        "agent",
        "langgraph",
        "roomos",
        "workflow",
        "embedding",
        "retrieval",
    ],
}


@dataclass
class ChunkSearchHit:
    memory: MemoryItem
    chunk: MemoryChunk
    score: float


def extract_terms(text: str) -> list[str]:
    if not text:
        return []

    normalized: list[str] = []
    compact = text.strip().lower()

    for token in ALNUM_TOKEN_RE.findall(compact):
        if token:
            normalized.append(token)

    for sequence in CHINESE_SEQ_RE.findall(compact):
        if len(sequence) <= 4:
            normalized.append(sequence)
            continue
        normalized.extend(sequence[index : index + 2] for index in range(len(sequence) - 1))

    return list(dict.fromkeys(token for token in normalized if token.strip()))


def summarize_chunk(text: str, limit: int = 96) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else f"{compact[:limit].rstrip()}..."


def split_into_chunks(text: str, *, target_size: int = 180) -> list[str]:
    compact = text.strip()
    if not compact:
        return []

    sentences = [item.strip() for item in SENTENCE_SPLIT_RE.split(compact) if item.strip()]
    if not sentences:
        return [compact]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = sentence if not current else f"{current}\u3002{sentence}"
        if len(candidate) <= target_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = sentence

    if current:
        chunks.append(current)

    return chunks or [compact]


def cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    if size == 0:
        return 0.0
    dot = sum(left[index] * right[index] for index in range(size))
    left_norm = sqrt(sum(value * value for value in left[:size]))
    right_norm = sqrt(sum(value * value for value in right[:size]))
    if left_norm <= 1e-12 or right_norm <= 1e-12:
        return 0.0
    return dot / (left_norm * right_norm)


class ChunkService:
    def rebuild_chunks_for_memory(self, db: Session, memory: MemoryItem) -> list[MemoryChunk]:
        source_text = memory.content_clean or memory.content_raw
        raw_chunks = split_into_chunks(source_text)
        if not raw_chunks:
            raw_chunks = [source_text]
        embeddings = embedding_service.embed_texts(raw_chunks)

        chunk_models = [
            MemoryChunk(
                user_id=memory.user_id,
                memory_id=memory.id,
                chunk_index=index,
                chunk_text=chunk_text,
                chunk_summary=summarize_chunk(chunk_text),
                embedding=embeddings[index] if index < len(embeddings) else None,
                token_count=len(extract_terms(chunk_text)),
                keywords=extract_terms(chunk_text)[:32],
                meta_payload={
                    "memory_title": memory.title,
                    "category": memory.category,
                    "embedding_signature": embedding_service.signature(),
                },
            )
            for index, chunk_text in enumerate(raw_chunks)
        ]
        return memory_chunk_repository.replace_for_memory(db, memory.id, chunk_models)

    def ensure_chunks_for_memory(self, db: Session, memory: MemoryItem) -> list[MemoryChunk]:
        if memory_chunk_repository.count_for_memory(db, memory.id) > 0:
            return memory_chunk_repository.list_for_memory(db, memory.id)
        return self.rebuild_chunks_for_memory(db, memory)

    def backfill_missing_chunks(self, db: Session, memories: list[MemoryItem]) -> int:
        rebuilt = 0
        for memory in memories:
            if memory_chunk_repository.count_for_memory(db, memory.id) == 0:
                self.rebuild_chunks_for_memory(db, memory)
                rebuilt += 1
        return rebuilt

    def refresh_chunk_embeddings(self, db: Session) -> int:
        signature = embedding_service.signature()
        chunks = [
            chunk
            for chunk in memory_chunk_repository.list_all(db)
            if chunk.embedding is None or (chunk.meta_payload or {}).get("embedding_signature") != signature
        ]
        if not chunks:
            return 0

        embeddings = embedding_service.embed_texts([chunk.chunk_text for chunk in chunks])
        for chunk, embedding in zip(chunks, embeddings, strict=False):
            chunk.embedding = embedding
            chunk.meta_payload = {
                **(chunk.meta_payload or {}),
                "embedding_signature": signature,
            }

        db.flush()
        return len(chunks)

    def retrieve_relevant_chunks(
        self,
        db: Session,
        user_id: uuid.UUID,
        memories: list[MemoryItem],
        question: str,
        *,
        limit: int = 5,
        memory_ids: list[uuid.UUID] | None = None,
        dedupe_by_memory: bool = True,
    ) -> list[ChunkSearchHit]:
        query_terms = extract_terms(question)
        query_embedding = embedding_service.embed_text(question) if question.strip() else []
        if not query_terms and not any(query_embedding):
            return []

        memory_map = {memory.id: memory for memory in memories}
        hits: list[ChunkSearchHit] = []
        route = query_router_service.route(question, "memory_only")

        scope_memory_ids = memory_ids or list(memory_map.keys())
        pg_hits = memory_chunk_repository.search_similar_chunks(
            db,
            user_id,
            query_embedding,
            limit=limit * 4,
            memory_ids=scope_memory_ids,
        )
        if pg_hits:
            for chunk, similarity in pg_hits:
                memory = memory_map.get(chunk.memory_id)
                if memory is None:
                    continue
                score = self._score_chunk(
                    question=question,
                    query_terms=query_terms,
                    chunk=chunk,
                    memory=memory,
                    vector_score=similarity,
                    intent=route.intent,
                )
                hits.append(ChunkSearchHit(memory=memory, chunk=chunk, score=float(score)))
            return self._dedupe_and_sort(hits, limit, dedupe_by_memory=dedupe_by_memory)

        if scope_memory_ids and len(scope_memory_ids) == 1:
            chunks = memory_chunk_repository.list_for_memory(db, scope_memory_ids[0])
        else:
            chunks = memory_chunk_repository.list_for_user(db, user_id)
        for chunk in chunks:
            memory = memory_map.get(chunk.memory_id)
            if memory is None:
                continue
            vector_score = cosine_similarity(query_embedding, chunk.embedding)
            score = self._score_chunk(
                question=question,
                query_terms=query_terms,
                chunk=chunk,
                memory=memory,
                vector_score=vector_score,
                intent=route.intent,
            )
            if score > 0.1:
                hits.append(ChunkSearchHit(memory=memory, chunk=chunk, score=float(score)))
        return self._dedupe_and_sort(hits, limit, dedupe_by_memory=dedupe_by_memory)

    def _score_chunk(
        self,
        *,
        question: str,
        query_terms: list[str],
        chunk: MemoryChunk,
        memory: MemoryItem,
        vector_score: float,
        intent: str,
    ) -> float:
        chunk_text = chunk.chunk_text.lower()
        title_text = (memory.title or "").lower()
        summary_text = (memory.content_summary or "").lower()
        chunk_terms = [term.lower() for term in (chunk.keywords or [])]
        overlap = len(set(query_terms) & set(chunk_terms))
        text_bonus = sum(1 for term in query_terms if term in chunk_text or term in title_text or term in summary_text)
        score = vector_score * 4.2 + overlap * 1.2 + text_bonus * 0.65
        if title_text and title_text in question.lower():
            score += 8.0

        if "\u6700\u8fd1" in question and memory.event_time is not None:
            score += 0.35
        if intent in INTENT_KEYWORDS:
            score += self._intent_boost(intent, f"{chunk_text} {title_text} {summary_text}")
        if intent == "learning" and memory.category == "learning":
            score += 0.45
        return score

    def _intent_boost(self, intent: str, haystack: str) -> float:
        keywords = INTENT_KEYWORDS.get(intent, [])
        matches = sum(1 for keyword in keywords if keyword.lower() in haystack)
        if matches == 0:
            return 0.0
        return min(3.0, matches * 0.8)

    def _dedupe_and_sort(self, hits: list[ChunkSearchHit], limit: int, *, dedupe_by_memory: bool = True) -> list[ChunkSearchHit]:
        hits.sort(key=lambda item: (item.score, item.memory.created_at), reverse=True)
        result: list[ChunkSearchHit] = []
        seen_memory_ids: set[uuid.UUID] = set()
        for hit in hits:
            if dedupe_by_memory and hit.memory.id in seen_memory_ids:
                continue
            seen_memory_ids.add(hit.memory.id)
            result.append(hit)
            if len(result) >= limit:
                break
        return result


chunk_service = ChunkService()
