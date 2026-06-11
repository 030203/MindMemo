from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class QAContextMessage(BaseModel):
    role: str
    content: str


class QARequest(BaseModel):
    question: str
    mode: str = "memory_only"
    conversation_context: list[QAContextMessage] = Field(default_factory=list)
    context_memory_id: str | None = None
    context_title: str | None = None
    context_text: str | None = None
    active_doc_id: str | None = None
    active_record_id: str | None = None
    selected_text: str | None = None
    visible_page: int | None = None
    visible_chunk_ids: list[str] = Field(default_factory=list)
    active_context_type: Literal["document", "record", "none"] = "none"


class CitationItem(BaseModel):
    type: str
    id: str
    title: str
    snippet: str
    score: float


class RetrievalTraceCandidate(BaseModel):
    rank: int
    memory_id: str
    chunk_id: str
    title: str
    category: str
    score: float
    snippet: str
    raw_hit_score: float | None = None
    normalized_hit_score: float | None = None
    entered_direct_window: bool | None = None
    entered_rerank: bool | None = None
    final_selected: bool | None = None
    exclusion_reason: str | None = None
    exclusion_reason_detail: str | None = None
    citation_source: str | None = None
    final_score: float | None = None


class RetrievalTraceResponse(BaseModel):
    id: str
    question: str
    mode: str
    retrieval_strategy: str
    answer_source: str
    candidates: list[RetrievalTraceCandidate] = Field(default_factory=list)
    selected_citations: list = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    created_at: str


class AgentRunStepResponse(BaseModel):
    id: str
    step_index: int
    key: str
    label: str
    status: str
    detail: str
    metric: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: float | None = None
    error_message: str | None = None
    metadata: dict = Field(default_factory=dict)


class AgentRunResponse(BaseModel):
    id: str
    retrieval_trace_id: str | None = None
    run_type: str
    question: str
    mode: str
    status: str
    answer_source: str
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: float | None = None
    error_message: str | None = None
    metadata: dict = Field(default_factory=dict)
    steps: list[AgentRunStepResponse] = Field(default_factory=list)


class QAResponseData(BaseModel):
    answer: str
    citations: list[CitationItem] = Field(default_factory=list)
    suggested_followups: list[str] = Field(default_factory=list)
    trace: RetrievalTraceResponse | None = None
