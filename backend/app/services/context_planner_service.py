from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import uuid

from app.models.memory import MemoryChunk, MemoryItem
from app.schemas.qa import QARequest
from app.services.chunk_service import ChunkSearchHit
from app.services.query_router_service import QueryRoute


FULL_CONTEXT_DIRECT_CHAR_LIMIT = 8000
LOCAL_CONTEXT_CHAR_LIMIT = 9000
SUMMARY_MAP_CHUNK_CHAR_LIMIT = 5500

TEMPORAL_MARKER_RE = re.compile(
    r"(\d{1,2}[:：]\d{2}|\d{1,2}\s*点(?:\d{1,2}\s*分)?|早上|上午|中午|下午|放学|傍晚|晚上|夜里|凌晨|今天|这一天|周[一二三四五六日天])"
)
HEADING_RE = re.compile(r"^\s*(?:#{1,6}\s*)?([^\n。！？!?]{2,40})(?:[:：]|$)")


@dataclass(frozen=True)
class ActiveContext:
    active_doc_id: str | None = None
    active_record_id: str | None = None
    context_memory_id: str | None = None
    selected_text: str | None = None
    visible_page: int | None = None
    visible_chunk_ids: tuple[str, ...] = ()
    active_context_type: str = "none"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ContextPack:
    context_blocks: list[str]
    chunk_ids: list[str]
    token_count: int
    content_length: int


class ContextPlannerService:
    def active_context_from_payload(self, payload: QARequest) -> ActiveContext:
        active_type = payload.active_context_type or "none"
        if active_type == "none":
            if payload.active_doc_id:
                active_type = "document"
            elif payload.active_record_id or payload.context_memory_id:
                active_type = "record"

        return ActiveContext(
            active_doc_id=payload.active_doc_id,
            active_record_id=payload.active_record_id,
            context_memory_id=payload.context_memory_id,
            selected_text=(payload.selected_text or "").strip() or None,
            visible_page=payload.visible_page,
            visible_chunk_ids=tuple(payload.visible_chunk_ids or []),
            active_context_type=active_type,
        )

    def has_active_context(self, active_context: ActiveContext) -> bool:
        return bool(
            active_context.active_context_type in {"document", "record"}
            or active_context.active_doc_id
            or active_context.active_record_id
            or active_context.context_memory_id
            or active_context.selected_text
        )

    def target_memory_id(self, route: QueryRoute, active_context: ActiveContext) -> uuid.UUID | None:
        candidate = None
        if route.scope == "current_document":
            candidate = active_context.active_doc_id or active_context.active_record_id or active_context.context_memory_id
        elif route.scope == "current_record":
            candidate = active_context.active_record_id or active_context.context_memory_id or active_context.active_doc_id
        if not candidate:
            return None
        try:
            return uuid.UUID(candidate)
        except (TypeError, ValueError):
            return None

    def router_result(self, route: QueryRoute) -> dict:
        return route.as_dict()

    def estimate_tokens(self, text: str) -> int:
        compact = " ".join((text or "").split())
        if not compact:
            return 0
        ascii_like = sum(1 for char in compact if char.isascii())
        non_ascii = max(len(compact) - ascii_like, 0)
        return max(1, ascii_like // 4 + non_ascii // 2)

    def pack_chunks(
        self,
        memory: MemoryItem,
        chunks: list[MemoryChunk],
        *,
        max_chars: int = LOCAL_CONTEXT_CHAR_LIMIT,
        prefix: str = "当前上下文片段",
    ) -> ContextPack:
        context_blocks: list[str] = []
        chunk_ids: list[str] = []
        content_length = 0
        ordered_chunks = sorted(chunks, key=lambda item: item.chunk_index)
        for chunk in ordered_chunks:
            block = "\n".join(
                [
                    f"{prefix}：是",
                    f"标题：{memory.title or '未命名记录'}",
                    f"chunk_id：{chunk.id}",
                    f"chunk_index：{chunk.chunk_index}",
                    f"内容：\n{chunk.chunk_text}",
                ]
            )
            next_length = content_length + len(block)
            if context_blocks and next_length > max_chars:
                break
            context_blocks.append(block)
            chunk_ids.append(str(chunk.id))
            content_length = next_length
        return ContextPack(
            context_blocks=context_blocks,
            chunk_ids=chunk_ids,
            token_count=self.estimate_tokens("\n\n".join(context_blocks)),
            content_length=content_length,
        )

    def expand_neighbor_chunks(
        self,
        hits: list[ChunkSearchHit],
        all_chunks: list[MemoryChunk],
        *,
        neighbor_window: int = 1,
        max_seed_hits: int = 5,
        max_chunks: int = 14,
    ) -> list[MemoryChunk]:
        if not hits:
            return []
        chunks_by_index = {chunk.chunk_index: chunk for chunk in all_chunks}
        selected_indexes: set[int] = set()
        for hit in sorted(hits, key=lambda item: item.score, reverse=True)[:max_seed_hits]:
            for index in range(hit.chunk.chunk_index - neighbor_window, hit.chunk.chunk_index + neighbor_window + 1):
                if index in chunks_by_index:
                    selected_indexes.add(index)
        ordered = [chunks_by_index[index] for index in sorted(selected_indexes)]
        return ordered[:max_chunks]

    def visible_neighbor_chunks(self, visible_chunk_ids: tuple[str, ...], all_chunks: list[MemoryChunk]) -> list[MemoryChunk]:
        if not visible_chunk_ids:
            return []
        visible_ids = set(visible_chunk_ids)
        selected_indexes = {
            chunk.chunk_index
            for chunk in all_chunks
            if str(chunk.id) in visible_ids
        }
        if not selected_indexes:
            return []
        chunks_by_index = {chunk.chunk_index: chunk for chunk in all_chunks}
        expanded_indexes: set[int] = set()
        for index in selected_indexes:
            for expanded_index in range(index - 1, index + 2):
                if expanded_index in chunks_by_index:
                    expanded_indexes.add(expanded_index)
        return [chunks_by_index[index] for index in sorted(expanded_indexes)]

    def map_summary_groups(self, chunks: list[MemoryChunk]) -> list[list[MemoryChunk]]:
        groups: list[list[MemoryChunk]] = []
        current: list[MemoryChunk] = []
        current_size = 0
        for chunk in sorted(chunks, key=lambda item: item.chunk_index):
            chunk_size = len(chunk.chunk_text)
            if current and current_size + chunk_size > SUMMARY_MAP_CHUNK_CHAR_LIMIT:
                groups.append(current)
                current = []
                current_size = 0
            current.append(chunk)
            current_size += chunk_size
        if current:
            groups.append(current)
        return groups

    def coverage_markers(self, chunks: list[MemoryChunk]) -> list[str]:
        markers: list[str] = []
        for chunk in sorted(chunks, key=lambda item: item.chunk_index):
            for marker in TEMPORAL_MARKER_RE.findall(chunk.chunk_text):
                self._append_unique(markers, marker.strip())
            for line in chunk.chunk_text.splitlines():
                match = HEADING_RE.match(line.strip())
                if match:
                    candidate = match.group(1).strip(" #*-")
                    if 2 <= len(candidate) <= 28:
                        self._append_unique(markers, candidate)
            if len(markers) >= 24:
                break
        return markers[:24]

    def coverage_check(self, answer: str, markers: list[str]) -> dict:
        if not markers:
            return {"marker_count": 0, "covered": [], "missing": [], "coverage_ratio": 1.0, "passed": True}
        covered = [marker for marker in markers if marker and marker in answer]
        missing = [marker for marker in markers if marker and marker not in answer]
        ratio = len(covered) / max(len(markers), 1)
        return {
            "marker_count": len(markers),
            "covered": covered,
            "missing": missing,
            "coverage_ratio": round(ratio, 4),
            "passed": ratio >= 0.45 or len(missing) <= 3,
        }

    def make_debug_metadata(
        self,
        *,
        user_query: str,
        active_context: ActiveContext,
        router_result: dict,
        context_mode: str,
        retrieved_chunk_ids: list[str],
        expanded_chunk_ids: list[str],
        final_context_token_count: int,
        llm_input_content_length: int,
    ) -> dict:
        return {
            "user_query": user_query,
            "active_context": active_context.as_dict(),
            "router_result": router_result,
            "context_mode": context_mode,
            "retrieved_chunk_ids": retrieved_chunk_ids,
            "expanded_chunk_ids": expanded_chunk_ids,
            "final_context_token_count": final_context_token_count,
            "llm_input_content_length": llm_input_content_length,
            "triggered_full_summary": context_mode == "full_summary",
            "triggered_exhaustive_extract": context_mode == "exhaustive_extract",
        }

    def _append_unique(self, values: list[str], value: str) -> None:
        if value and value not in values:
            values.append(value)


context_planner_service = ContextPlannerService()
