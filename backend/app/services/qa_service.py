from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from math import exp
from time import perf_counter

from sqlalchemy.orm import Session

from app.repos.fact_repo import fact_repository
from app.repos.memory_repo import memory_repository
from app.schemas.qa import CitationItem, QARequest, QAResponseData
from app.services.chunk_service import ChunkSearchHit, chunk_service, extract_terms
from app.services.context_planner_service import (
    FULL_CONTEXT_DIRECT_CHAR_LIMIT,
    ActiveContext,
    context_planner_service,
)
from app.services.dashboard_service import dashboard_service
from app.services.fact_insight_service import TimeWindow, fact_insight_service
from app.services.llm_answer_service import LLMAnswerResult, llm_answer_service
from app.services.memory_relation_service import memory_relation_service
from app.services.query_router_service import QueryRoute, query_router_service
from app.services.retrieval_trace_service import retrieval_trace_service
from app.services.settings_service import settings_service
from app.services.weather_service import weather_service
from app.services.web_search_service import web_search_service

DIRECT_CITATION_WINDOW = 3
MIN_DIRECT_SCORE = 0.25
FINAL_CITATION_SCORE_FLOOR = 0.18
CONTEXT_RETRIEVAL_LIMIT = 8
CONTEXT_STRICT_NOT_FOUND_SCORE = 0.18

logger = logging.getLogger(__name__)


class QAService:
    DOCUMENT_SOURCE_TYPES = {"file", "pdf", "url"}

    def answer_question(self, db: Session, user_id: uuid.UUID, payload: QARequest) -> QAResponseData:
        context_strategy_response = self._answer_active_context_question(db, user_id, payload)
        if context_strategy_response is not None:
            return context_strategy_response

        inline_context_response = self._answer_inline_context_question(db, user_id, payload)
        if inline_context_response is not None:
            return inline_context_response

        if payload.context_memory_id:
            context_response = self._answer_context_memory_question(db, user_id, payload)
            if context_response is not None:
                return context_response

        effective_question = self._build_effective_question(payload)
        effective_payload = payload.model_copy(update={"question": effective_question})
        workflow_steps: list[dict] = []
        route: QueryRoute | None = None
        hits = []
        citations: list[CitationItem] = []
        answer_source = "memory_rag"
        related_memories = None
        citation_score_breakdown: list[dict] | None = None

        if effective_question and effective_question != payload.question:
            workflow_steps.append(
                self._make_workflow_step(
                    key="followup_rewrite",
                    label="Follow-up Rewrite",
                    status="done",
                    detail="Rewrote the follow-up into a retrieval-ready question using recent conversation context.",
                    metric="context_used",
                )
            )

        try:
            route, route_duration_ms = self._timed_call(
                lambda: query_router_service.route(effective_payload.question, effective_payload.mode)
            )
            workflow_steps.append(
                self._make_workflow_step(
                    key="query_route",
                    label="Query Route",
                    status="done",
                    detail=route.reason,
                    metric=route.intent,
                    duration_ms=route_duration_ms,
                )
            )
            if route.route == "clarify":
                answer_source = "clarify"
                response = self._build_clarification_response(payload.question, route)
                workflow_steps.append(
                    self._make_workflow_step(
                        key="answer_generation",
                        label="Answer Generation",
                        status="done",
                        detail=self._workflow_answer_detail(answer_source, len(response.citations)),
                        metric=answer_source,
                    )
                )
                response.trace = self._record_trace(
                    db,
                    user_id=user_id,
                    payload=payload,
                    hits=[],
                    citations=response.citations,
                    answer_source=answer_source,
                    route=route,
                    effective_question=effective_question,
                    workflow_steps=workflow_steps,
                    execution_plan=self._build_execution_plan(
                        original_question=payload.question,
                        effective_question=effective_payload.question,
                        mode=effective_payload.mode,
                        route=route,
                    ),
                )
                return response

            if route.route == "direct":
                answer_source = "direct_answer"
                response = self._build_direct_response(payload.question, route)
                workflow_steps.append(
                    self._make_workflow_step(
                        key="answer_generation",
                        label="Answer Generation",
                        status="done",
                        detail=self._workflow_answer_detail(answer_source, len(response.citations)),
                        metric=answer_source,
                    )
                )
                response.trace = self._record_trace(
                    db,
                    user_id=user_id,
                    payload=payload,
                    hits=[],
                    citations=response.citations,
                    answer_source=answer_source,
                    route=route,
                    effective_question=effective_question,
                    workflow_steps=workflow_steps,
                    execution_plan=self._build_execution_plan(
                        original_question=payload.question,
                        effective_question=effective_payload.question,
                        mode=effective_payload.mode,
                        route=route,
                    ),
                )
                return response

            execution_plan, planning_duration_ms = self._timed_call(
                lambda: self._build_execution_plan(
                    original_question=payload.question,
                    effective_question=effective_payload.question,
                    mode=effective_payload.mode,
                    route=route,
                )
            )
            workflow_steps.append(
                self._make_workflow_step(
                    key="execution_plan",
                    label="Execution Plan",
                    status="done",
                    detail=execution_plan["summary"],
                    metric=str(len(execution_plan["subquestions"])),
                    duration_ms=planning_duration_ms,
                    metadata={
                        "subquestions": execution_plan["subquestions"],
                        "tools": execution_plan["tools"],
                    },
                )
            )
            memories = memory_repository.list_for_user(db, user_id)
            if route.should_retrieve:
                hits, retrieval_duration_ms = self._timed_call(
                    lambda: chunk_service.retrieve_relevant_chunks(db, user_id, memories, effective_payload.question, limit=5)
                )
                workflow_steps.append(
                    self._make_workflow_step(
                        key="chunk_retrieval",
                        label="Chunk Retrieval",
                        status="done",
                        detail=f"Retrieved {len(hits)} candidate chunks from memory.",
                        metric=str(len(hits)),
                        duration_ms=retrieval_duration_ms,
                    )
                )
            else:
                workflow_steps.append(
                    self._make_workflow_step(
                        key="chunk_retrieval",
                        label="Chunk Retrieval",
                        status="done",
                        detail="Skipped memory retrieval for this route.",
                        metric="skipped",
                    )
                )
            selected_memories = self._select_memories(memories, hits)
            citations = self._build_memory_citations(selected_memories, hits)

            if route.route == "weather":
                response, weather_duration_ms = self._timed_call(lambda: self._answer_weather_question(effective_payload.question, citations))
                if response is not None:
                    answer_source = "weather_tool"
                    workflow_steps.append(
                        self._make_workflow_step(
                            key="answer_generation",
                            label="Answer Generation",
                            status="done",
                            detail=self._workflow_answer_detail(answer_source, len(response.citations)),
                            metric=answer_source,
                            duration_ms=weather_duration_ms,
                        )
                    )
                    response.trace = self._record_trace(
                        db,
                        user_id=user_id,
                        payload=payload,
                        hits=hits,
                        citations=response.citations,
                        answer_source=answer_source,
                        route=route,
                        effective_question=effective_question,
                        workflow_steps=workflow_steps,
                        execution_plan=execution_plan,
                    )
                    return response
                response = QAResponseData(
                    answer="这是一个实时天气问题，需要天气工具或联网查询。当前没有可用的天气数据源，所以我不会把它误解释成当前记录内容。",
                    citations=[],
                    suggested_followups=["北京天气怎么样", "联网查一下北京天气", "只看当前记录回答"],
                )
                workflow_steps.append(
                    self._make_workflow_step(
                        key="answer_generation",
                        label="Answer Generation",
                        status="done",
                        detail=self._workflow_answer_detail("weather_tool_unavailable", 0),
                        metric="weather_tool_unavailable",
                        duration_ms=weather_duration_ms,
                    )
                )
                response.trace = self._record_trace(
                    db,
                    user_id=user_id,
                    payload=payload,
                    hits=[],
                    citations=[],
                    answer_source="weather_tool_unavailable",
                    route=route,
                    effective_question=effective_question,
                    workflow_steps=workflow_steps,
                    execution_plan=execution_plan,
                )
                return response

            if route.route == "fact":
                fact_response = self._answer_fact_question(
                    db,
                    user_id,
                    effective_payload,
                    hits,
                    citations,
                    route,
                    trace_payload=payload,
                    workflow_steps=workflow_steps,
                    execution_plan=execution_plan,
                )
                if fact_response is not None:
                    return fact_response

            if route.route == "insight":
                insight_response, insight_duration_ms = self._timed_call(
                    lambda: self._answer_insight_question(db, user_id, effective_payload.question)
                )
                if insight_response is not None:
                    answer_source = "insight_agent"
                    workflow_steps.append(
                        self._make_workflow_step(
                            key="answer_generation",
                            label="Answer Generation",
                            status="done",
                            detail=self._workflow_answer_detail(answer_source, len(insight_response.citations)),
                            metric=answer_source,
                            duration_ms=insight_duration_ms,
                        )
                    )
                    insight_response.trace = self._record_trace(
                        db,
                        user_id=user_id,
                        payload=payload,
                        hits=hits,
                        citations=insight_response.citations,
                        answer_source=answer_source,
                        route=route,
                        effective_question=effective_question,
                        workflow_steps=workflow_steps,
                        execution_plan=execution_plan,
                    )
                    return insight_response

            if route.route == "web":
                response, web_duration_ms = self._timed_call(lambda: self._answer_web_question(effective_payload.question, citations))
                if response is not None:
                    answer_source = "web_tool"
                    workflow_steps.append(
                        self._make_workflow_step(
                            key="answer_generation",
                            label="Answer Generation",
                            status="done",
                            detail=self._workflow_answer_detail(answer_source, len(response.citations)),
                            metric=answer_source,
                            duration_ms=web_duration_ms,
                        )
                    )
                    response.trace = self._record_trace(
                        db,
                        user_id=user_id,
                        payload=payload,
                        hits=hits,
                        citations=response.citations,
                        answer_source=answer_source,
                        route=route,
                        effective_question=effective_question,
                        workflow_steps=workflow_steps,
                        execution_plan=execution_plan,
                    )
                    return response
                response = QAResponseData(
                    answer="这是一个需要外部信息的问题。当前联网搜索工具不可用，所以我不会改成根据你的个人记录猜答案。",
                    citations=[],
                    suggested_followups=["只根据我的记录回答", "换一个更具体的问题", "稍后再联网查"],
                )
                workflow_steps.append(
                    self._make_workflow_step(
                        key="answer_generation",
                        label="Answer Generation",
                        status="done",
                        detail=self._workflow_answer_detail("web_tool_unavailable", 0),
                        metric="web_tool_unavailable",
                        duration_ms=web_duration_ms,
                    )
                )
                response.trace = self._record_trace(
                    db,
                    user_id=user_id,
                    payload=payload,
                    hits=[],
                    citations=[],
                    answer_source="web_tool_unavailable",
                    route=route,
                    effective_question=effective_question,
                    workflow_steps=workflow_steps,
                    execution_plan=execution_plan,
                )
                return response

            fact_response = self._answer_fact_question(
                db,
                user_id,
                effective_payload,
                hits,
                citations,
                route,
                trace_payload=payload,
                workflow_steps=workflow_steps,
                execution_plan=execution_plan,
            )
            if fact_response is not None:
                return fact_response

            related_memories, relation_duration_ms = self._timed_call(lambda: self._expand_related_memories(db, user_id, selected_memories))
            if related_memories:
                workflow_steps.append(
                    self._make_workflow_step(
                        key="relation_expand",
                        label="Relation Expansion",
                        status="done",
                        detail=f"Expanded {len(related_memories)} related memories via relation edges.",
                        metric=str(len(related_memories)),
                        duration_ms=relation_duration_ms,
                    )
                )
            (expanded_citations, citation_score_breakdown), rerank_duration_ms = self._timed_call(
                lambda: self._rerank_memory_citations(db, user_id, effective_payload.question, citations, hits, related_memories)
            )
            selected_count = sum(1 for item in citation_score_breakdown if item.get("selected") is True)
            workflow_steps.append(
                self._make_workflow_step(
                    key="citation_rerank",
                    label="Citation Rerank",
                    status="done",
                    detail=(
                        "Reranked citations using direct hit strength, relation support, recency, "
                        f"and fact confidence; kept {selected_count} citations."
                    ),
                    metric=str(selected_count),
                    duration_ms=rerank_duration_ms,
                )
            )
            answer, answer_duration_ms = self._timed_call(
                lambda: self._build_memory_answer(
                    db,
                    user_id,
                    effective_payload,
                    selected_memories,
                    hits,
                    expanded_citations,
                    related_memories,
                )
            )
            workflow_steps.append(
                self._make_workflow_step(
                    key="answer_generation",
                    label="Answer Generation",
                    status="done",
                    detail=self._workflow_answer_detail(answer_source, len(expanded_citations)),
                    metric=answer_source,
                    duration_ms=answer_duration_ms,
                )
            )
            trace = self._record_trace(
                db,
                user_id=user_id,
                payload=payload,
                hits=hits,
                citations=expanded_citations,
                answer_source=answer_source,
                route=route,
                related_memories=related_memories,
                citation_score_breakdown=citation_score_breakdown,
                effective_question=effective_question,
                workflow_steps=workflow_steps,
                execution_plan=execution_plan,
            )
            return QAResponseData(
                answer=answer,
                citations=expanded_citations,
                suggested_followups=[
                    "\u53ea\u770b\u6700\u8fd1\u4e00\u5468\u7684\u4efb\u52a1\u63a8\u8fdb\u60c5\u51b5",
                    "\u628a\u548c LangGraph \u76f8\u5173\u7684\u8bb0\u5f55\u5168\u90e8\u5217\u51fa\u6765",
                    "\u6839\u636e\u5f53\u524d\u4efb\u52a1\u7ed9\u6211\u4e00\u4e2a\u4eca\u65e5\u6267\u884c\u987a\u5e8f",
                ],
                trace=trace,
            )
        except Exception as exc:
            if route is not None:
                workflow_steps.append(
                    self._make_workflow_step(
                        key="answer_generation",
                        label="Answer Generation",
                        status="failed",
                        detail="The QA workflow failed before a final answer could be generated.",
                        metric=answer_source,
                        error_message=str(exc),
                    )
                )
                self._record_trace(
                    db,
                    user_id=user_id,
                    payload=payload,
                    hits=hits,
                    citations=citations,
                    answer_source=answer_source,
                    route=route,
                    related_memories=related_memories,
                    citation_score_breakdown=citation_score_breakdown,
                    effective_question=effective_question,
                    workflow_steps=workflow_steps,
                    agent_error_message=str(exc),
                    execution_plan=execution_plan if "execution_plan" in locals() else None,
                )
            raise

    def _answer_active_context_question(self, db: Session, user_id: uuid.UUID, payload: QARequest) -> QAResponseData | None:
        active_context = context_planner_service.active_context_from_payload(payload)
        if not context_planner_service.has_active_context(active_context):
            return None

        effective_question = self._build_effective_question(payload)
        question = effective_question or payload.question
        route = query_router_service.route(question, payload.mode, active_context.as_dict())
        if route.route == "clarify":
            return self._finalize_simple_route_response(
                db,
                user_id,
                payload,
                route,
                effective_question=effective_question,
                response=self._build_clarification_response(payload.question, route),
                answer_source="clarify",
            )
        if route.route == "direct":
            return None
        if route.route in {"weather", "web"}:
            return None
        if route.route == "document_op":
            return self._answer_active_context_document_op(
                db,
                user_id,
                payload,
                route,
                active_context,
                effective_question=effective_question,
            )
        if route.scope == "global" or not route.should_use_active_context:
            return None

        target_memory_id = context_planner_service.target_memory_id(route, active_context)
        memory = memory_repository.get_for_user(db, user_id, target_memory_id) if target_memory_id is not None else None

        if route.context_mode == "direct_selected_text" and active_context.selected_text:
            return self._answer_direct_selected_text(
                db,
                user_id,
                payload,
                route,
                active_context,
                memory,
                effective_question=effective_question,
            )

        if memory is None:
            return None

        chunks = chunk_service.ensure_chunks_for_memory(db, memory)
        if self._content_is_attachment_only(memory.content_raw or ""):
            return self._answer_attachment_only_context(
                db,
                user_id,
                payload,
                route,
                active_context,
                memory,
                effective_question=effective_question,
            )

        if route.context_mode == "full_summary":
            return self._answer_context_full_summary(
                db,
                user_id,
                payload,
                route,
                active_context,
                memory,
                chunks,
                effective_question=effective_question,
            )
        if route.context_mode == "exhaustive_extract":
            return self._answer_context_exhaustive_extract(
                db,
                user_id,
                payload,
                route,
                active_context,
                memory,
                chunks,
                effective_question=effective_question,
            )
        if route.context_mode == "global_then_local":
            return self._answer_context_global_then_local(
                db,
                user_id,
                payload,
                route,
                active_context,
                memory,
                chunks,
                effective_question=effective_question,
            )
        return self._answer_context_local_qa(
            db,
            user_id,
            payload,
            route,
            active_context,
            memory,
            chunks,
            effective_question=effective_question,
        )

    def _answer_attachment_only_context(
        self,
        db: Session,
        user_id: uuid.UUID,
        payload: QARequest,
        route: QueryRoute,
        active_context: ActiveContext,
        memory,
        *,
        effective_question: str | None,
    ) -> QAResponseData:
        title = memory.title or "未命名记录"
        scope_label = "文件" if route.scope == "current_document" else "记录"
        answer = (
            f"当前{scope_label}《{title}》目前只有附件信息，还没有解析到可问答的正文内容。"
            "我不会改去检索其他记录来凑答案；请先重新导入可解析文本，或把正文粘贴进记录里。"
        )
        citation = self._context_anchor_citation(memory, route)
        debug_metadata = context_planner_service.make_debug_metadata(
            user_query=payload.question,
            active_context=active_context,
            router_result=context_planner_service.router_result(route),
            context_mode=route.context_mode,
            retrieved_chunk_ids=[],
            expanded_chunk_ids=[],
            final_context_token_count=0,
            llm_input_content_length=0,
        )
        self._log_context_strategy_debug(debug_metadata)
        workflow_steps = self._context_workflow_steps(
            route=route,
            detail="The active context has no parsed body text, so the answer stayed anchored to the current item.",
            retrieved_count=0,
            expanded_count=0,
        )
        trace = self._record_context_trace(
            db,
            user_id=user_id,
            payload=payload,
            route=route,
            active_context=active_context,
            hits=[],
            citations=[citation],
            answer_source=f"context_{route.context_mode}",
            effective_question=effective_question,
            workflow_steps=workflow_steps,
            debug_metadata=debug_metadata,
        )
        return QAResponseData(answer=answer, citations=[citation], suggested_followups=["重新导入正文后总结", "只看当前记录提取待办"], trace=trace)

    def _answer_active_context_document_op(
        self,
        db: Session,
        user_id: uuid.UUID,
        payload: QARequest,
        route: QueryRoute,
        active_context: ActiveContext,
        *,
        effective_question: str | None,
    ) -> QAResponseData | None:
        target_memory_id = context_planner_service.target_memory_id(route, active_context)
        memory = memory_repository.get_for_user(db, user_id, target_memory_id) if target_memory_id is not None else None
        if memory is None:
            return None
        chunks = chunk_service.ensure_chunks_for_memory(db, memory)
        return self._answer_context_document_op(
            db,
            user_id,
            payload,
            route,
            active_context,
            memory,
            chunks,
            effective_question=effective_question,
        )

    def _answer_context_document_op(
        self,
        db: Session,
        user_id: uuid.UUID,
        payload: QARequest,
        route: QueryRoute,
        active_context: ActiveContext,
        memory,
        chunks,
        *,
        effective_question: str | None,
    ) -> QAResponseData:
        if route.intent == "doc_summary":
            return self._answer_context_full_summary(
                db,
                user_id,
                payload,
                route,
                active_context,
                memory,
                chunks,
                effective_question=effective_question,
            )
        if route.intent == "doc_extract":
            return self._answer_context_exhaustive_extract(
                db,
                user_id,
                payload,
                route,
                active_context,
                memory,
                chunks,
                effective_question=effective_question,
            )
        return self._answer_context_transform(
            db,
            user_id,
            payload,
            route,
            active_context,
            memory,
            chunks,
            effective_question=effective_question,
        )

    def _answer_context_transform(
        self,
        db: Session,
        user_id: uuid.UUID,
        payload: QARequest,
        route: QueryRoute,
        active_context: ActiveContext,
        memory,
        chunks,
        *,
        effective_question: str | None,
    ) -> QAResponseData:
        content = (memory.content_clean or memory.content_raw or "").strip()
        title = memory.title or "未命名记录"
        user_settings = settings_service.get_settings(db, user_id)
        transform_question = effective_question or payload.question
        context_block = "\n".join(
            [
                "当前文件/记录全文：是",
                f"标题：{title}",
                f"内容：\n{content[:FULL_CONTEXT_DIRECT_CHAR_LIMIT]}",
            ]
        )
        llm_answer = llm_answer_service.generate_grounded_answer(
            question=(
                f"{transform_question}\n\n"
                "请只基于当前文件/记录全文完成这次内容转换。"
                "如果用户要求改写、翻译、整理成周报或邮件，就直接输出转换结果，不要额外解释。"
            ),
            provider=user_settings.llm_provider,
            model=user_settings.llm_model,
            context_blocks=[context_block],
        )
        answer = llm_answer or self._build_transform_fallback(route.intent, title, content, chunks)
        citation = self._context_anchor_citation(memory, route, snippet=self._snippet_from_chunks(chunks))
        all_hits = [ChunkSearchHit(memory=memory, chunk=chunk, score=1.0) for chunk in chunks]
        debug_metadata = context_planner_service.make_debug_metadata(
            user_query=payload.question,
            active_context=active_context,
            router_result=context_planner_service.router_result(route),
            context_mode=route.context_mode,
            retrieved_chunk_ids=[],
            expanded_chunk_ids=[str(chunk.id) for chunk in chunks],
            final_context_token_count=context_planner_service.estimate_tokens(context_block),
            llm_input_content_length=len(context_block),
        )
        workflow_steps = self._context_workflow_steps(
            route=route,
            detail="Read the full active document/record and transformed it for the requested output format.",
            retrieved_count=0,
            expanded_count=len(chunks),
        )
        trace = self._record_context_trace(
            db,
            user_id=user_id,
            payload=payload,
            route=route,
            active_context=active_context,
            hits=all_hits,
            citations=[citation],
            answer_source=f"context_{route.intent}",
            effective_question=effective_question,
            workflow_steps=workflow_steps,
            debug_metadata=debug_metadata,
        )
        return QAResponseData(
            answer=answer,
            citations=[citation],
            suggested_followups=["继续调整语气", "再精简一点", "提取成待办"],
            trace=trace,
        )

    def _answer_context_local_qa(
        self,
        db: Session,
        user_id: uuid.UUID,
        payload: QARequest,
        route: QueryRoute,
        active_context: ActiveContext,
        memory,
        chunks,
        *,
        effective_question: str | None,
    ) -> QAResponseData:
        question = effective_question or payload.question
        hits, retrieval_duration_ms = self._timed_call(
            lambda: chunk_service.retrieve_relevant_chunks(
                db,
                user_id,
                [memory],
                question,
                limit=CONTEXT_RETRIEVAL_LIMIT,
                memory_ids=[memory.id],
                dedupe_by_memory=False,
            )
        )
        expanded_chunks = context_planner_service.expand_neighbor_chunks(hits, chunks)
        if not expanded_chunks:
            expanded_chunks = context_planner_service.visible_neighbor_chunks(active_context.visible_chunk_ids, chunks)
        context_pack = context_planner_service.pack_chunks(memory, expanded_chunks, prefix="当前文件/记录局部片段")
        retrieved_chunk_ids = [str(hit.chunk.id) for hit in hits]
        expanded_chunk_ids = [str(chunk.id) for chunk in expanded_chunks]

        user_settings = settings_service.get_settings(db, user_id)
        strict_question = (
            f"{question}\n\n"
            "回答要求：只基于当前文件/记录的给定片段回答；如果片段里找不到依据，请明确说“当前文件/记录中没有找到”。"
        )
        llm_result = llm_answer_service.generate_grounded_answer_result(
            question=strict_question,
            provider=user_settings.llm_provider,
            model=user_settings.llm_model,
            context_blocks=context_pack.context_blocks,
            answer_mode=route.answer_mode,
        )
        answer = llm_result.answer or self._build_local_qa_fallback(memory.title or "未命名记录", question, hits, expanded_chunks)
        citation = self._context_anchor_citation(memory, route, snippet=self._snippet_from_chunks(expanded_chunks))
        debug_metadata = context_planner_service.make_debug_metadata(
            user_query=payload.question,
            active_context=active_context,
            router_result=context_planner_service.router_result(route),
            context_mode=route.context_mode,
            retrieved_chunk_ids=retrieved_chunk_ids,
            expanded_chunk_ids=expanded_chunk_ids,
            final_context_token_count=context_pack.token_count,
            llm_input_content_length=context_pack.content_length,
        )
        self._attach_llm_debug_metadata(debug_metadata, llm_result)
        self._log_context_strategy_debug(debug_metadata)
        workflow_steps = self._context_workflow_steps(
            route=route,
            detail="Retrieved only within the active document/record, reranked by local score, expanded neighbor chunks, and packed them in source order.",
            retrieved_count=len(retrieved_chunk_ids),
            expanded_count=len(expanded_chunk_ids),
            duration_ms=retrieval_duration_ms,
        )
        trace = self._record_context_trace(
            db,
            user_id=user_id,
            payload=payload,
            route=route,
            active_context=active_context,
            hits=hits,
            citations=[citation],
            answer_source="context_local_qa",
            effective_question=effective_question,
            workflow_steps=workflow_steps,
            debug_metadata=debug_metadata,
        )
        return QAResponseData(answer=answer, citations=[citation], suggested_followups=["继续问这个文件里的细节", "总结整个当前文件"], trace=trace)

    def _answer_context_full_summary(
        self,
        db: Session,
        user_id: uuid.UUID,
        payload: QARequest,
        route: QueryRoute,
        active_context: ActiveContext,
        memory,
        chunks,
        *,
        effective_question: str | None,
    ) -> QAResponseData:
        question = effective_question or payload.question
        content = (memory.content_clean or memory.content_raw or "").strip()
        user_settings = settings_service.get_settings(db, user_id)
        chunk_ids = [str(chunk.id) for chunk in chunks]
        coverage_markers = context_planner_service.coverage_markers(chunks)
        used_map_reduce = len(content) > FULL_CONTEXT_DIRECT_CHAR_LIMIT
        answer_char_limit = self._extract_answer_char_limit(question)
        output_instruction = self._summary_output_instruction(answer_char_limit)
        summary_repair_reason: str | None = None

        if not used_map_reduce:
            context_block = "\n".join(
                [
                    "当前文件/记录全文：是",
                    f"标题：{memory.title or '未命名记录'}",
                    f"内容：\n{content}",
                ]
            )
            llm_answer = llm_answer_service.generate_grounded_answer(
                question=(
                    f"{question}\n\n"
                    "请总结当前文件/记录的全文，必须覆盖主要阶段、主要事件、主要观点；不要只总结开头。"
                    "忽略“附件：”这类文件元数据行，不要把原文片段列表当作答案。"
                    "输出综合性的总结，不要用“覆盖全部 N 个片段”或逐片段编号来代替总结。"
                    f"{output_instruction}"
                ),
                provider=user_settings.llm_provider,
                model=user_settings.llm_model,
                context_blocks=[context_block],
                answer_mode=route.answer_mode,
            )
            answer = llm_answer or self._build_full_coverage_summary(memory, chunks)
            final_token_count = context_planner_service.estimate_tokens(context_block)
            input_content_length = len(context_block)
        else:
            map_summaries: list[str] = []
            for index, group in enumerate(context_planner_service.map_summary_groups(chunks), start=1):
                group_pack = context_planner_service.pack_chunks(memory, group, max_chars=FULL_CONTEXT_DIRECT_CHAR_LIMIT, prefix=f"第 {index} 组全文片段")
                group_summary = llm_answer_service.generate_grounded_answer(
                    question=(
                        "请总结这一组片段，保留时间点、章节标题、关键事件、待办和结论。"
                        "忽略“附件：”这类文件元数据行，不要照抄原文。"
                    ),
                    provider=user_settings.llm_provider,
                    model=user_settings.llm_model,
                    context_blocks=group_pack.context_blocks,
                    answer_mode="summarize",
                )
                map_summaries.append(group_summary or self._build_group_summary(group))
            reduce_blocks = [f"第 {index} 组摘要：\n{summary}" for index, summary in enumerate(map_summaries, start=1)]
            llm_answer = llm_answer_service.generate_grounded_answer(
                question=(
                    f"{question}\n\n"
                    "请基于所有分组摘要做最终全文总结，必须覆盖全文主要阶段、主要事件、主要观点，并按原文顺序组织。"
                    "不要输出片段清单，不要照抄原文，不要用“覆盖全部 N 个片段”或逐片段编号来代替总结。"
                    f"{output_instruction}"
                ),
                provider=user_settings.llm_provider,
                model=user_settings.llm_model,
                context_blocks=reduce_blocks,
                answer_mode=route.answer_mode,
            )
            answer = llm_answer or self._build_full_coverage_summary(memory, chunks)
            final_token_count = context_planner_service.estimate_tokens("\n\n".join(reduce_blocks))
            input_content_length = sum(len(block) for block in reduce_blocks)

        if self._looks_like_chunk_inventory_summary(answer):
            summary_repair_reason = "chunk_inventory"
            if answer_char_limit:
                answer = self._build_constrained_coverage_summary(memory, chunks, max_chars=answer_char_limit)
            else:
                answer = self._build_synthesized_coverage_summary(memory, chunks)

        coverage = context_planner_service.coverage_check(answer, coverage_markers)
        if not coverage["passed"] and coverage["missing"]:
            summary_repair_reason = summary_repair_reason or "coverage_markers"
            if answer_char_limit:
                answer = self._build_constrained_coverage_summary(memory, chunks, max_chars=answer_char_limit)
            else:
                answer = self._build_synthesized_coverage_summary(memory, chunks)
            coverage = context_planner_service.coverage_check(answer, coverage_markers)
        chunk_coverage = self._summary_chunk_coverage(answer, chunks)
        if not chunk_coverage["passed"]:
            summary_repair_reason = summary_repair_reason or "chunk_coverage"
            if answer_char_limit:
                answer = self._build_constrained_coverage_summary(memory, chunks, max_chars=answer_char_limit)
            else:
                answer = self._build_synthesized_coverage_summary(memory, chunks)
            chunk_coverage = self._summary_chunk_coverage(answer, chunks)
        if self._looks_like_chunk_inventory_summary(answer):
            summary_repair_reason = summary_repair_reason or "chunk_inventory_after_repair"
            if answer_char_limit:
                answer = self._build_constrained_coverage_summary(memory, chunks, max_chars=answer_char_limit)
            else:
                answer = self._build_synthesized_coverage_summary(memory, chunks)
            coverage = context_planner_service.coverage_check(answer, coverage_markers)
            chunk_coverage = self._summary_chunk_coverage(answer, chunks)
        if answer_char_limit and len(answer) > answer_char_limit:
            summary_repair_reason = summary_repair_reason or "char_limit"
            answer = self._build_constrained_coverage_summary(memory, chunks, max_chars=answer_char_limit)
            coverage = context_planner_service.coverage_check(answer, coverage_markers)
            chunk_coverage = self._summary_chunk_coverage(answer, chunks)

        citation = self._context_anchor_citation(memory, route, snippet=self._snippet_from_chunks(chunks))
        hits = [ChunkSearchHit(memory=memory, chunk=chunk, score=1.0) for chunk in chunks]
        debug_metadata = context_planner_service.make_debug_metadata(
            user_query=payload.question,
            active_context=active_context,
            router_result=context_planner_service.router_result(route),
            context_mode=route.context_mode,
            retrieved_chunk_ids=[],
            expanded_chunk_ids=chunk_ids,
            final_context_token_count=final_token_count,
            llm_input_content_length=input_content_length,
        )
        debug_metadata["coverage_check"] = coverage
        debug_metadata["chunk_coverage_check"] = chunk_coverage
        debug_metadata["used_map_reduce_summary"] = used_map_reduce
        debug_metadata["answer_char_limit"] = answer_char_limit
        debug_metadata["summary_repaired"] = summary_repair_reason is not None
        debug_metadata["summary_repair_reason"] = summary_repair_reason
        self._log_context_strategy_debug(debug_metadata)
        workflow_steps = self._context_workflow_steps(
            route=route,
            detail="Read the full active document/record and summarized either directly or via map-reduce over every chunk.",
            retrieved_count=0,
            expanded_count=len(chunk_ids),
        )
        workflow_steps.insert(
            2,
            self._make_workflow_step(
                key="coverage_check",
                label="Coverage Check",
                status="done",
                detail=f"Checked {coverage['marker_count']} coverage markers; ratio={coverage['coverage_ratio']}.",
                metric="passed" if coverage["passed"] else "needs_attention",
                metadata=coverage,
            ),
        )
        trace = self._record_context_trace(
            db,
            user_id=user_id,
            payload=payload,
            route=route,
            active_context=active_context,
            hits=hits,
            citations=[citation],
            answer_source="context_full_summary",
            effective_question=effective_question,
            workflow_steps=workflow_steps,
            debug_metadata=debug_metadata,
        )
        return QAResponseData(answer=answer, citations=[citation], suggested_followups=["列出所有待办", "按时间线整理这份内容"], trace=trace)

    def _answer_context_exhaustive_extract(
        self,
        db: Session,
        user_id: uuid.UUID,
        payload: QARequest,
        route: QueryRoute,
        active_context: ActiveContext,
        memory,
        chunks,
        *,
        effective_question: str | None,
    ) -> QAResponseData:
        question = effective_question or payload.question
        items = self._extract_exhaustive_items(question, chunks)
        if items:
            lines = [f"{index}. {item}" for index, item in enumerate(items, start=1)]
            answer = f"我已扫描当前文件/记录的全部 {len(chunks)} 个 chunk，按原文顺序整理如下：\n" + "\n".join(lines)
        else:
            answer = f"我已扫描当前文件/记录的全部 {len(chunks)} 个 chunk，没有找到和“{payload.question}”明确匹配的项目。"
        all_text = "\n".join(chunk.chunk_text for chunk in chunks)
        chunk_ids = [str(chunk.id) for chunk in chunks]
        citation = self._context_anchor_citation(memory, route, snippet=self._snippet_from_chunks(chunks))
        hits = [ChunkSearchHit(memory=memory, chunk=chunk, score=1.0) for chunk in chunks]
        debug_metadata = context_planner_service.make_debug_metadata(
            user_query=payload.question,
            active_context=active_context,
            router_result=context_planner_service.router_result(route),
            context_mode=route.context_mode,
            retrieved_chunk_ids=[],
            expanded_chunk_ids=chunk_ids,
            final_context_token_count=context_planner_service.estimate_tokens(all_text),
            llm_input_content_length=len(all_text),
        )
        debug_metadata["extracted_item_count"] = len(items)
        self._log_context_strategy_debug(debug_metadata)
        workflow_steps = self._context_workflow_steps(
            route=route,
            detail="Scanned every chunk in the active document/record and merged duplicate extraction candidates in source order.",
            retrieved_count=0,
            expanded_count=len(chunk_ids),
        )
        trace = self._record_context_trace(
            db,
            user_id=user_id,
            payload=payload,
            route=route,
            active_context=active_context,
            hits=hits,
            citations=[citation],
            answer_source="context_exhaustive_extract",
            effective_question=effective_question,
            workflow_steps=workflow_steps,
            debug_metadata=debug_metadata,
        )
        return QAResponseData(answer=answer, citations=[citation], suggested_followups=["再按优先级整理", "把这些转成待办"], trace=trace)

    def _answer_context_global_then_local(
        self,
        db: Session,
        user_id: uuid.UUID,
        payload: QARequest,
        route: QueryRoute,
        active_context: ActiveContext,
        memory,
        chunks,
        *,
        effective_question: str | None,
    ) -> QAResponseData:
        question = effective_question or payload.question
        hits = chunk_service.retrieve_relevant_chunks(
            db,
            user_id,
            [memory],
            question,
            limit=CONTEXT_RETRIEVAL_LIMIT,
            memory_ids=[memory.id],
            dedupe_by_memory=False,
        )
        expanded_chunks = context_planner_service.expand_neighbor_chunks(hits, chunks)
        outline = memory.content_summary or self._build_group_summary(chunks[: min(len(chunks), 6)])
        local_pack = context_planner_service.pack_chunks(memory, expanded_chunks, prefix="当前文件/记录局部证据")
        context_blocks = [
            f"当前文件/记录整体理解：\n标题：{memory.title or '未命名记录'}\n概要：{outline}",
            *local_pack.context_blocks,
        ]
        user_settings = settings_service.get_settings(db, user_id)
        llm_answer = llm_answer_service.generate_grounded_answer(
            question=(
                f"{question}\n\n"
                "请先给出整体理解，再用当前文件/记录中的局部证据解释。不要引用其他文件或记录。"
            ),
            provider=user_settings.llm_provider,
            model=user_settings.llm_model,
            context_blocks=context_blocks,
            answer_mode=route.answer_mode,
        )
        answer = llm_answer or self._build_global_then_local_fallback(outline, expanded_chunks)
        citation = self._context_anchor_citation(memory, route, snippet=self._snippet_from_chunks(expanded_chunks or chunks))
        retrieved_chunk_ids = [str(hit.chunk.id) for hit in hits]
        expanded_chunk_ids = [str(chunk.id) for chunk in expanded_chunks]
        debug_metadata = context_planner_service.make_debug_metadata(
            user_query=payload.question,
            active_context=active_context,
            router_result=context_planner_service.router_result(route),
            context_mode=route.context_mode,
            retrieved_chunk_ids=retrieved_chunk_ids,
            expanded_chunk_ids=expanded_chunk_ids,
            final_context_token_count=context_planner_service.estimate_tokens("\n\n".join(context_blocks)),
            llm_input_content_length=sum(len(block) for block in context_blocks),
        )
        self._log_context_strategy_debug(debug_metadata)
        workflow_steps = self._context_workflow_steps(
            route=route,
            detail="Combined the active document/record outline with local evidence retrieved only inside the same context.",
            retrieved_count=len(retrieved_chunk_ids),
            expanded_count=len(expanded_chunk_ids),
        )
        trace = self._record_context_trace(
            db,
            user_id=user_id,
            payload=payload,
            route=route,
            active_context=active_context,
            hits=hits,
            citations=[citation],
            answer_source="context_global_then_local",
            effective_question=effective_question,
            workflow_steps=workflow_steps,
            debug_metadata=debug_metadata,
        )
        return QAResponseData(answer=answer, citations=[citation], suggested_followups=["只解释这个证据", "完整总结当前文件"], trace=trace)

    def _answer_direct_selected_text(
        self,
        db: Session,
        user_id: uuid.UUID,
        payload: QARequest,
        route: QueryRoute,
        active_context: ActiveContext,
        memory,
        *,
        effective_question: str | None,
    ) -> QAResponseData:
        selected_text = active_context.selected_text or ""
        chunks = chunk_service.ensure_chunks_for_memory(db, memory) if memory is not None else []
        neighbor_chunks = context_planner_service.visible_neighbor_chunks(active_context.visible_chunk_ids, chunks)
        neighbor_pack = context_planner_service.pack_chunks(memory, neighbor_chunks, prefix="选中文本相邻片段") if memory is not None else None
        context_blocks = [f"用户选中的文本：\n{selected_text}"]
        if neighbor_pack is not None:
            context_blocks.extend(neighbor_pack.context_blocks[:3])
        user_settings = settings_service.get_settings(db, user_id)
        question = effective_question or payload.question
        llm_answer = llm_answer_service.generate_grounded_answer(
            question=(
                f"{question}\n\n"
                "请优先解释用户选中的文本；只有必要时才参考相邻片段，不要默认检索全库。"
            ),
            provider=user_settings.llm_provider,
            model=user_settings.llm_model,
            context_blocks=context_blocks,
        )
        answer = llm_answer or self._build_selected_text_fallback(selected_text, question)
        citation = (
            self._context_anchor_citation(memory, route, snippet=selected_text[:180])
            if memory is not None
            else CitationItem(type="memory", id="selected_text:inline", title="选中文本", snippet=selected_text[:180], score=1.0)
        )
        hits = [ChunkSearchHit(memory=memory, chunk=chunk, score=1.0) for chunk in neighbor_chunks] if memory is not None else []
        expanded_chunk_ids = [str(chunk.id) for chunk in neighbor_chunks]
        llm_input = "\n\n".join(context_blocks)
        debug_metadata = context_planner_service.make_debug_metadata(
            user_query=payload.question,
            active_context=active_context,
            router_result=context_planner_service.router_result(route),
            context_mode=route.context_mode,
            retrieved_chunk_ids=[],
            expanded_chunk_ids=expanded_chunk_ids,
            final_context_token_count=context_planner_service.estimate_tokens(llm_input),
            llm_input_content_length=len(llm_input),
        )
        self._log_context_strategy_debug(debug_metadata)
        workflow_steps = self._context_workflow_steps(
            route=route,
            detail="Answered from selected_text first and only added visible neighbor chunks when provided.",
            retrieved_count=0,
            expanded_count=len(expanded_chunk_ids),
        )
        trace = self._record_context_trace(
            db,
            user_id=user_id,
            payload=payload,
            route=route,
            active_context=active_context,
            hits=hits,
            citations=[citation],
            answer_source="context_direct_selected_text",
            effective_question=effective_question,
            workflow_steps=workflow_steps,
            debug_metadata=debug_metadata,
        )
        return QAResponseData(answer=answer, citations=[citation], suggested_followups=["继续解释下一句", "把这段改写得更清楚"], trace=trace)

    def _answer_inline_context_question(self, db: Session, user_id: uuid.UUID, payload: QARequest) -> QAResponseData | None:
        title = (payload.context_title or "").strip()
        content = (payload.context_text or "").strip()
        if payload.context_memory_id or not content:
            return None

        effective_question = self._build_effective_question(payload)
        anchor_title = title or "当前上下文记录"
        compact_content = " ".join(content.split())
        anchor_citation = CitationItem(
            type="memory",
            id=f"inline:{anchor_title}",
            title=anchor_title,
            snippet=compact_content[:180] or anchor_title,
            score=0.96,
        )
        workflow_steps: list[dict] = [
            self._make_workflow_step(
                key="inline_context",
                label="Use Visible Context",
                status="done",
                detail="Answered from the visible context text selected in the current UI.",
                metric="inline_context",
            )
        ]
        if effective_question and effective_question != payload.question:
            workflow_steps.append(
                self._make_workflow_step(
                    key="followup_rewrite",
                    label="Follow-up Rewrite",
                    status="done",
                    detail="Rewrote the follow-up into a retrieval-ready question using recent conversation context.",
                    metric="context_used",
                )
            )

        user_settings = settings_service.get_settings(db, user_id)
        context_block = f"标题：{anchor_title}\n内容：\n{content[:6000]}"
        answer = llm_answer_service.generate_grounded_answer(
            question=effective_question or payload.question,
            provider=user_settings.llm_provider,
            model=user_settings.llm_model,
            context_blocks=[context_block],
            answer_mode="grounded_qa",
        )
        if not answer:
            answer = self._build_local_context_answer(anchor_title, content, effective_question or payload.question)

        workflow_steps.append(
            self._make_workflow_step(
                key="answer_generation",
                label="Answer Generation",
                status="done",
                detail="Generated an answer grounded only in the visible selected context.",
                metric="inline_context",
            )
        )
        trace = self._record_trace(
            db,
            user_id=user_id,
            payload=payload,
            hits=[],
            citations=[anchor_citation],
            answer_source="inline_context",
            route=QueryRoute(route="memory", intent="inline_context", reason="Answered from the visible selected context."),
            effective_question=effective_question,
            workflow_steps=workflow_steps,
            execution_plan={
                "planner_version": "rule_based_v3",
                "summary": "Answer from the visible selected context only.",
                "route": "memory",
                "intent": "inline_context",
                "mode": payload.mode,
                "subquestions": [
                    self._planned_subquestion(
                        question=f"Read visible selected context: {anchor_title}",
                        tool="ui_context",
                        reason="The user asked about the currently selected context block.",
                    )
                ],
                "tools": ["ui_context", "llm_answer_service"],
                "context_packing": {"strategy": "visible_context_only", "max_direct_hits": 1},
            },
        )
        return QAResponseData(
            answer=answer,
            citations=[anchor_citation],
            suggested_followups=["总结一下", "提炼关键点", "拆成待办"],
            trace=trace,
        )

    def _answer_context_memory_question(self, db: Session, user_id: uuid.UUID, payload: QARequest) -> QAResponseData | None:
        if not payload.context_memory_id or not self._is_uuid(payload.context_memory_id):
            return None

        memory = memory_repository.get_for_user(db, user_id, uuid.UUID(payload.context_memory_id))
        if memory is None:
            return None

        title = memory.title or "未命名记录"
        content = (memory.content_raw or "").strip()
        compact_content = " ".join(content.split())
        effective_question = self._build_effective_question(payload)
        active_context = ActiveContext(
            active_record_id=str(memory.id),
            context_memory_id=str(memory.id),
            selected_text=(payload.selected_text or "").strip() or None,
            visible_page=payload.visible_page,
            visible_chunk_ids=tuple(payload.visible_chunk_ids or []),
            active_context_type="record",
        )
        context_route = query_router_service.route(effective_question or payload.question, payload.mode, active_context.as_dict())
        if context_route.route == "clarify":
            return self._finalize_simple_route_response(
                db,
                user_id,
                payload,
                context_route,
                effective_question=effective_question,
                response=self._build_clarification_response(payload.question, context_route),
                answer_source="clarify",
            )
        if context_route.route == "direct":
            return None
        if context_route.route in {"weather", "web"}:
            return None
        if context_route.route == "document_op":
            chunks = chunk_service.ensure_chunks_for_memory(db, memory)
            return self._answer_context_document_op(
                db,
                user_id,
                payload,
                context_route,
                active_context,
                memory,
                chunks,
                effective_question=effective_question,
            )
        if context_route.scope != "global" and context_route.context_mode in {"full_summary", "exhaustive_extract", "global_then_local"}:
            chunks = chunk_service.ensure_chunks_for_memory(db, memory)
            if context_route.context_mode == "full_summary":
                return self._answer_context_full_summary(
                    db,
                    user_id,
                    payload,
                    context_route,
                    active_context,
                    memory,
                    chunks,
                    effective_question=effective_question,
                )
            if context_route.context_mode == "exhaustive_extract":
                return self._answer_context_exhaustive_extract(
                    db,
                    user_id,
                    payload,
                    context_route,
                    active_context,
                    memory,
                    chunks,
                    effective_question=effective_question,
                )
            return self._answer_context_global_then_local(
                db,
                user_id,
                payload,
                context_route,
                active_context,
                memory,
                chunks,
                effective_question=effective_question,
            )
        anchor_citation = CitationItem(
            type="memory",
            id=str(memory.id),
            title=title,
            snippet=compact_content[:180] or title,
            score=1.0,
        )
        workflow_steps: list[dict] = [
            self._make_workflow_step(
                key="context_memory",
                label="Use Selected Memory",
                status="done",
                detail="Started from the memory explicitly selected by the user.",
                metric=str(memory.id),
            )
        ]
        if effective_question and effective_question != payload.question:
            workflow_steps.append(
                self._make_workflow_step(
                    key="followup_rewrite",
                    label="Follow-up Rewrite",
                    status="done",
                    detail="Rewrote the follow-up into a retrieval-ready question using recent conversation context.",
                    metric="context_used",
                )
            )

        if self._content_is_attachment_only(content):
            answer = (
                f"这条记录目前只有附件信息，还没有解析到正文内容，所以我不能可靠地总结《{title}》。"
                "请重新上传 Markdown / TXT 文档，或把文档正文粘贴进输入框；之后我会基于正文总结，而不是拿其他记忆来凑答案。"
            )
            workflow_steps.append(
                self._make_workflow_step(
                    key="answer_generation",
                    label="Answer Generation",
                    status="done",
                    detail="Answered with an attachment-only safeguard because the selected memory has no parsed body text.",
                    metric="context_memory",
                )
            )
            trace = self._record_trace(
                db,
                user_id=user_id,
                payload=payload,
                hits=[],
                citations=[anchor_citation],
                answer_source="context_memory",
                route=QueryRoute(route="memory", intent="context_memory", reason="Answered from an explicitly selected memory."),
                effective_question=effective_question,
                workflow_steps=workflow_steps,
                execution_plan={
                    "planner_version": "rule_based_v3",
                    "summary": "Answer from the explicitly selected memory only.",
                    "route": "memory",
                    "intent": "context_memory",
                    "mode": payload.mode,
                    "subquestions": [
                        self._planned_subquestion(
                            question=f"Read selected memory: {title}",
                            tool="memory_repository",
                            reason="The user asked about a specific record.",
                        )
                    ],
                    "tools": ["memory_repository"],
                    "context_packing": {"strategy": "selected_memory_only", "max_direct_hits": 1},
                },
            )
            return QAResponseData(
                answer=answer,
                citations=[anchor_citation],
                suggested_followups=["总结一下", "提炼关键点", "拆成待办"],
                trace=trace,
            )

        expand_retrieval = self._selected_memory_needs_retrieval(payload.question, effective_question)
        if not expand_retrieval:
            user_settings = settings_service.get_settings(db, user_id)
            context_block = (
                f"标题：{title}\n"
                f"类别：{memory.category}\n"
                f"来源类型：{memory.source_type}\n"
                f"内容：\n{content[:6000]}"
            )
            answer = llm_answer_service.generate_grounded_answer(
                question=effective_question or payload.question,
                provider=user_settings.llm_provider,
                model=user_settings.llm_model,
                context_blocks=[context_block],
                answer_mode="grounded_qa",
            )
            if not answer:
                answer = self._build_local_context_answer(title, content, effective_question or payload.question)
            workflow_steps.append(
                self._make_workflow_step(
                    key="context_strategy",
                    label="Context Strategy",
                    status="done",
                    detail="The question can be answered from the selected memory alone, so no extra retrieval was needed.",
                    metric="selected_memory_only",
                )
            )
            workflow_steps.append(
                self._make_workflow_step(
                    key="answer_generation",
                    label="Answer Generation",
                    status="done",
                    detail="Generated an answer grounded only in the selected memory.",
                    metric="context_memory",
                )
            )
            trace = self._record_trace(
                db,
                user_id=user_id,
                payload=payload,
                hits=[],
                citations=[anchor_citation],
                answer_source="context_memory",
                route=QueryRoute(route="memory", intent="context_memory", reason="Answered from an explicitly selected memory."),
                effective_question=effective_question,
                workflow_steps=workflow_steps,
                execution_plan={
                    "planner_version": "rule_based_v3",
                    "summary": "Answer from the explicitly selected memory only.",
                    "route": "memory",
                    "intent": "context_memory",
                    "mode": payload.mode,
                    "subquestions": [
                        self._planned_subquestion(
                            question=f"Read selected memory: {title}",
                            tool="memory_repository",
                            reason="The user asked about a specific record.",
                        )
                    ],
                    "tools": ["memory_repository", "llm_answer_service"],
                    "context_packing": {"strategy": "selected_memory_only", "max_direct_hits": 1},
                },
            )
            return QAResponseData(
                answer=answer,
                citations=[anchor_citation],
                suggested_followups=["总结一下", "提炼关键点", "拆成待办"],
                trace=trace,
            )

        workflow_steps.append(
            self._make_workflow_step(
                key="context_strategy",
                label="Context Strategy",
                status="done",
                detail="Detected that the question needs related memory retrieval before answering.",
                metric="selected_memory_plus_retrieval",
            )
        )
        all_memories = memory_repository.list_for_user(db, user_id)
        retrieval_query = self._build_selected_memory_retrieval_query(memory, effective_question or payload.question)
        hits, retrieval_duration_ms = self._timed_call(
            lambda: chunk_service.retrieve_relevant_chunks(db, user_id, all_memories, retrieval_query, limit=5)
        )
        workflow_steps.append(
            self._make_workflow_step(
                key="chunk_retrieval",
                label="Chunk Retrieval",
                status="done",
                detail=f"Retrieved {len(hits)} candidate chunks related to the selected memory.",
                metric=str(len(hits)),
                duration_ms=retrieval_duration_ms,
            )
        )
        selected_memories = self._selected_memory_anchor_first(memory, self._select_memories(all_memories, hits))
        related_memories, relation_duration_ms = self._timed_call(
            lambda: self._expand_related_memories(db, user_id, selected_memories)
        )
        if related_memories:
            workflow_steps.append(
                self._make_workflow_step(
                    key="relation_expand",
                    label="Relation Expansion",
                    status="done",
                    detail=f"Expanded {len(related_memories)} related memories from the selected memory context.",
                    metric=str(len(related_memories)),
                    duration_ms=relation_duration_ms,
                )
            )
        base_citations = self._merge_anchor_citation(
            anchor_citation,
            self._build_memory_citations(selected_memories, hits),
        )
        (reranked_citations, citation_score_breakdown), rerank_duration_ms = self._timed_call(
            lambda: self._rerank_memory_citations(
                db,
                user_id,
                effective_question or payload.question,
                base_citations,
                hits,
                related_memories,
            )
        )
        citations = self._merge_anchor_citation(anchor_citation, reranked_citations)
        workflow_steps.append(
            self._make_workflow_step(
                key="citation_rerank",
                label="Citation Rerank",
                status="done",
                detail=f"Kept {len(citations)} grounded citations after reranking.",
                metric=str(len(citations)),
                duration_ms=rerank_duration_ms,
            )
        )
        answer, answer_duration_ms = self._timed_call(
            lambda: self._build_selected_memory_rag_answer(
                db,
                user_id,
                payload,
                memory,
                selected_memories,
                hits,
                citations,
                related_memories,
                effective_question or payload.question,
            )
        )
        workflow_steps.append(
            self._make_workflow_step(
                key="answer_generation",
                label="Answer Generation",
                status="done",
                detail="Generated an answer grounded in the selected memory plus retrieved supporting context.",
                metric="context_memory_rag",
                duration_ms=answer_duration_ms,
            )
        )
        trace = self._record_trace(
            db,
            user_id=user_id,
            payload=payload,
            hits=hits,
            citations=citations,
            answer_source="context_memory_rag",
            route=QueryRoute(route="memory", intent="context_memory_rag", reason="Expanded retrieval around an explicitly selected memory."),
            related_memories=related_memories,
            citation_score_breakdown=citation_score_breakdown,
            effective_question=effective_question,
            workflow_steps=workflow_steps,
            execution_plan={
                "planner_version": "rule_based_v3",
                "summary": "Start from the selected memory, then retrieve supporting related memories before answering.",
                "route": "memory",
                "intent": "context_memory_rag",
                "mode": payload.mode,
                "subquestions": [
                    self._planned_subquestion(
                        question=f"Read selected memory: {title}",
                        tool="memory_repository",
                        reason="The user anchored the question on a specific record.",
                    ),
                    self._planned_subquestion(
                        question=f"Find supporting memories for: {effective_question or payload.question}",
                        tool="chunk_retrieval",
                        reason="The question asks for context that may extend beyond the selected record.",
                    ),
                ],
                "tools": ["memory_repository", "chunk_retrieval", "relation_expansion", "llm_answer_service"],
                "context_packing": {"strategy": "selected_memory_plus_retrieval", "max_direct_hits": 5},
            },
        )
        return QAResponseData(
            answer=answer,
            citations=citations,
            suggested_followups=["总结一下", "提炼关键点", "拆成待办"],
            trace=trace,
        )

    def _selected_memory_needs_retrieval(self, original_question: str, effective_question: str) -> bool:
        text = (effective_question or original_question or "").strip().lower()
        if not text:
            return False
        direct_only_markers = [
            "总结",
            "概括",
            "提炼",
            "关键点",
            "摘要",
            "润色",
            "改写",
            "翻译",
            "这条记录讲了什么",
            "总结一下",
        ]
        retrieval_markers = [
            "相关",
            "还有",
            "类似",
            "关联",
            "结合",
            "对比",
            "背景",
            "上下文",
            "延伸",
            "补充",
            "线索",
            "来源",
            "为什么",
            "下一步",
            "待办",
            "提醒",
            "最近",
            "趋势",
            "影响",
            "还有哪些",
            "what else",
            "related",
            "similar",
            "context",
            "background",
            "compare",
            "why",
            "next step",
        ]
        if any(marker in text for marker in retrieval_markers):
            return True
        if any(marker in text for marker in direct_only_markers):
            return False
        return self._looks_like_followup(original_question) and not any(marker in text for marker in direct_only_markers)

    def _build_selected_memory_retrieval_query(self, memory, question: str) -> str:
        summary = (memory.content_summary or memory.content_clean or memory.content_raw or "").strip()
        compact_summary = " ".join(summary.split())[:240]
        title = memory.title or "未命名记录"
        return "\n".join(
            [
                question.strip(),
                f"当前记录标题：{title}",
                f"当前记录摘要：{compact_summary}",
            ]
        ).strip()

    def _selected_memory_anchor_first(self, anchor_memory, memories):
        ordered = [anchor_memory]
        seen_memory_ids = {anchor_memory.id}
        for memory in memories:
            if memory.id in seen_memory_ids:
                continue
            ordered.append(memory)
            seen_memory_ids.add(memory.id)
        return ordered

    def _merge_anchor_citation(self, anchor_citation: CitationItem, citations: list[CitationItem], *, limit: int = 5) -> list[CitationItem]:
        merged = [anchor_citation]
        seen_ids = {anchor_citation.id}
        for citation in citations:
            if citation.id in seen_ids:
                continue
            merged.append(citation)
            seen_ids.add(citation.id)
            if len(merged) >= limit:
                break
        return merged

    def _build_selected_memory_rag_answer(
        self,
        db: Session,
        user_id: uuid.UUID,
        payload: QARequest,
        anchor_memory,
        memories,
        hits,
        citations,
        related_memories,
        effective_question: str,
    ) -> str:
        user_settings = settings_service.get_settings(db, user_id)
        title = anchor_memory.title or "未命名记录"
        content = (anchor_memory.content_raw or "").strip()
        anchor_block = (
            f"当前焦点记录：是\n"
            f"标题：{title}\n"
            f"类别：{anchor_memory.category}\n"
            f"来源类型：{anchor_memory.source_type}\n"
            f"内容：\n{content[:5000]}"
        )
        extra_blocks = self._build_context_blocks(memories, hits, citations, related_memories or [])
        context_blocks = [anchor_block]
        for block in extra_blocks:
            if f"标题：{title}" in block:
                continue
            context_blocks.append(block)
        answer = llm_answer_service.generate_grounded_answer(
            question=effective_question,
            provider=user_settings.llm_provider,
            model=user_settings.llm_model,
            context_blocks=context_blocks[:6],
            answer_mode="grounded_qa",
        )
        if answer:
            return answer
        if len(context_blocks) == 1:
            return self._build_local_context_answer(title, content, effective_question)
        return self._build_memory_answer(db, user_id, payload.model_copy(update={"question": effective_question}), memories, hits, citations, related_memories)

    def _context_anchor_citation(self, memory, route: QueryRoute, *, snippet: str | None = None, score: float = 1.0) -> CitationItem:
        scope_label = "当前文件" if route.scope == "current_document" else "当前记录"
        compact = " ".join((snippet or memory.content_summary or memory.content_clean or memory.content_raw or "").split())
        return CitationItem(
            type="memory",
            id=str(memory.id),
            title=f"{scope_label}：{memory.title or '未命名记录'}",
            snippet=compact[:220] or (memory.title or "未命名记录"),
            score=score,
        )

    def _snippet_from_chunks(self, chunks) -> str:
        snippets = []
        for chunk in chunks[:3]:
            text = " ".join((chunk.chunk_summary or chunk.chunk_text or "").split())
            if text:
                snippets.append(text[:120])
        return "；".join(snippets)

    def _build_local_qa_fallback(self, title: str, question: str, hits, expanded_chunks) -> str:
        if not hits or not expanded_chunks:
            return f"在当前文件/记录《{title}》中没有找到能回答这个问题的明确片段。"
        if max(float(hit.score) for hit in hits) < CONTEXT_STRICT_NOT_FOUND_SCORE:
            return f"在当前文件/记录《{title}》中没有找到足够明确的依据。"

        terms = [term.lower() for term in extract_terms(question)]
        candidate_sentences = []
        for chunk in expanded_chunks:
            for sentence in self._split_context_sentences(chunk.chunk_text):
                lowered = sentence.lower()
                score = sum(1 for term in terms if term and term in lowered)
                if score > 0:
                    candidate_sentences.append((score, chunk.chunk_index, sentence))
        if not candidate_sentences:
            excerpts = [self._compact_text(chunk.chunk_text, 140) for chunk in expanded_chunks[:3]]
            return f"当前文件/记录《{title}》里最相关的片段是：{'；'.join(excerpts)}"

        candidate_sentences.sort(key=lambda item: (-item[0], item[1]))
        evidence = "；".join(sentence for _, _, sentence in candidate_sentences[:3])
        return f"基于当前文件/记录《{title}》的局部片段，可以看到：{evidence}"

    def _extract_answer_char_limit(self, question: str) -> int | None:
        text = question or ""
        patterns = [
            r"(?:不超过|控制在|限制在|最多|不多于|少于)\s*(\d{1,4})\s*字",
            r"(\d{1,4})\s*字\s*(?:以内|之内|内)",
            r"(\d{1,4})\s*字",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            value = int(match.group(1))
            if value >= 10:
                return min(value, 2000)
        chinese_numbers = {
            "几十": 80,
            "一百": 100,
            "两百": 200,
            "二百": 200,
            "三百": 300,
            "五百": 500,
        }
        for marker, value in chinese_numbers.items():
            if marker in text and "字" in text:
                return value
        return None

    def _summary_output_instruction(self, answer_char_limit: int | None) -> str:
        if not answer_char_limit:
            return ""
        return (
            f"用户明确要求不超过 {answer_char_limit} 字，最终答案必须严格控制在 {answer_char_limit} 个中文字符以内；"
            "输出一段紧凑总结，不要分点，不要补充片段清单。"
        )

    def _build_constrained_coverage_summary(self, memory, chunks, *, max_chars: int) -> str:
        ordered_chunks = sorted(chunks, key=lambda item: item.chunk_index)
        fragments: list[str] = []
        for chunk in self._select_coverage_chunks(ordered_chunks, max_items=min(6, max(1, max_chars // 18))):
            fragments.extend(self._summary_fragments_from_text(chunk.chunk_text, max_items=2))
        if not fragments:
            content = self._strip_attachment_metadata(memory.content_clean or memory.content_raw or "")
            fragments = self._split_context_sentences(content)[:4]
        if not fragments:
            return f"《{memory.title or '当前内容'}》暂无可总结正文。"[:max_chars]

        for item_count in range(min(len(fragments), 6), 0, -1):
            budget_per_item = max(10, (max_chars - max(item_count - 1, 0)) // item_count)
            selected = self._select_evenly(fragments, item_count)
            candidate = "；".join(self._trim_fragment(fragment, budget_per_item) for fragment in selected)
            candidate = candidate.strip("；，、。 ")
            if len(candidate) <= max_chars:
                return candidate
        return self._trim_fragment(fragments[0], max_chars)

    def _build_synthesized_coverage_summary(self, memory, chunks, *, max_items: int = 14) -> str:
        title = memory.title or "当前内容"
        ordered_chunks = sorted(chunks, key=lambda item: item.chunk_index)
        fragments: list[str] = []

        for chunk in self._select_coverage_chunks(ordered_chunks, max_items=max_items):
            max_per_chunk = 4 if len(ordered_chunks) <= 3 else 2
            fragments.extend(self._summary_fragments_from_text(chunk.chunk_text, max_items=max_per_chunk))
        if not fragments:
            content = self._strip_attachment_metadata(memory.content_clean or memory.content_raw or "")
            fragments = self._select_evenly(self._split_context_sentences(content), max_items)

        deduped_fragments: list[str] = []
        seen: set[str] = set()
        for fragment in fragments:
            normalized = re.sub(r"\s+", "", fragment).lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped_fragments.append(fragment)
        if not deduped_fragments:
            return f"《{title}》暂无可总结正文。"

        clauses = [self._trim_fragment(fragment, 96) for fragment in self._select_evenly(deduped_fragments, max_items)]
        if len(clauses) == 1:
            return f"《{title}》主要讲：{clauses[0]}。"
        if len(clauses) == 2:
            return f"《{title}》主要围绕{clauses[0]}展开，并进一步提到{clauses[1]}。"

        connectors = ["随后", "接着", "进一步", "后续", "同时", "之后"]
        middle_parts = []
        for index, clause in enumerate(clauses[1:-1]):
            connector = connectors[min(index, len(connectors) - 1)]
            middle_parts.append(f"{connector}，{clause}")
        middle_text = "；".join(middle_parts)
        return (
            f"《{title}》主要围绕{clauses[0]}展开；"
            f"{middle_text}；最后，{clauses[-1]}。"
            "整体来看，这份内容的主线由这些阶段、事件和观点共同构成，而不是只停留在开头部分。"
        )

    def _looks_like_chunk_inventory_summary(self, answer: str) -> bool:
        compact = " ".join((answer or "").split())
        if not compact:
            return False
        lower_compact = compact.lower()
        has_chunk_marker = "片段" in compact or "chunk" in lower_compact
        has_inventory_phrase = any(
            marker in compact
            for marker in [
                "完整总结如下",
                "按原文顺序覆盖",
                "覆盖全部",
                "逐片段",
            ]
        )
        numbered_item = re.search(r"(?:^|[\n：:；;。])\s*\d+[.、]", answer or "") is not None
        return (has_chunk_marker and has_inventory_phrase) or (has_chunk_marker and numbered_item)

    def _is_low_information_summary_fragment(self, fragment: str) -> bool:
        normalized = fragment.strip(" 。；;，,：:")
        if normalized in {"思想汇报", "敬爱的党组织", "此致", "敬礼"}:
            return True
        return normalized.startswith(("汇报人", "汇报日期"))

    def _summary_fragments_from_text(self, text: str, *, max_items: int | None = None) -> list[str]:
        cleaned_text = self._strip_attachment_metadata(text)
        fragments: list[str] = []
        for sentence in self._split_context_sentences(cleaned_text):
            fragment = sentence.strip(" 。；;，,")
            if len(fragment) < 6 or self._is_low_information_summary_fragment(fragment):
                continue
            fragments.append(fragment)
            if max_items and len(fragments) >= max_items:
                break
        if fragments:
            return fragments
        compact = " ".join(cleaned_text.split()).strip()
        return [compact[:80]] if compact else []

    def _first_summary_fragment(self, text: str) -> str:
        fragments = self._summary_fragments_from_text(text, max_items=1)
        return fragments[0] if fragments else ""

    def _strip_attachment_metadata(self, text: str) -> str:
        lines = []
        for line in (text or "").replace("\r", "\n").splitlines():
            stripped = line.strip()
            if stripped.startswith("附件：") or stripped.startswith("附件:"):
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    def _select_evenly(self, items: list[str], max_items: int) -> list[str]:
        if len(items) <= max_items:
            return items
        if max_items <= 1:
            return [items[0]]
        selected: list[str] = []
        seen_indexes: set[int] = set()
        for slot in range(max_items):
            index = round(slot * (len(items) - 1) / (max_items - 1))
            if index in seen_indexes:
                continue
            seen_indexes.add(index)
            selected.append(items[index])
        return selected

    def _trim_fragment(self, text: str, limit: int) -> str:
        compact = " ".join((text or "").split()).strip(" 。；;，,")
        if len(compact) <= limit:
            return compact
        if limit <= 1:
            return compact[:limit]
        return compact[: max(1, limit - 1)].rstrip("，、；; ") + "…"

    def _build_full_coverage_summary(self, memory, chunks) -> str:
        ordered_chunks = sorted(chunks, key=lambda item: item.chunk_index)
        if not ordered_chunks:
            content = (memory.content_clean or memory.content_raw or "").strip()
            return self._build_local_context_answer(memory.title or "未命名记录", content, "总结")
        return self._build_synthesized_coverage_summary(memory, ordered_chunks)

    def _summary_chunk_coverage(self, answer: str, chunks) -> dict:
        ordered_chunks = sorted(chunks, key=lambda item: item.chunk_index)
        if len(ordered_chunks) <= 1:
            return {"chunk_count": len(ordered_chunks), "covered_indexes": [chunk.chunk_index for chunk in ordered_chunks], "missing_indexes": [], "coverage_ratio": 1.0, "passed": True}

        covered_indexes: list[int] = []
        missing_indexes: list[int] = []
        answer_text = (answer or "").lower()
        for chunk in ordered_chunks:
            terms = self._chunk_coverage_terms(chunk)
            if terms and any(term.lower() in answer_text for term in terms):
                covered_indexes.append(chunk.chunk_index)
            else:
                missing_indexes.append(chunk.chunk_index)
        ratio = len(covered_indexes) / max(len(ordered_chunks), 1)
        last_index = ordered_chunks[-1].chunk_index
        tail_covered = last_index in set(covered_indexes)
        return {
            "chunk_count": len(ordered_chunks),
            "covered_indexes": covered_indexes,
            "missing_indexes": missing_indexes,
            "coverage_ratio": round(ratio, 4),
            "tail_covered": tail_covered,
            "passed": ratio >= 0.65 and tail_covered,
        }

    def _chunk_coverage_terms(self, chunk) -> list[str]:
        raw_terms = list(chunk.keywords or []) or extract_terms(chunk.chunk_text)
        terms: list[str] = []
        stop_terms = {
            "一个",
            "一些",
            "以及",
            "但是",
            "然后",
            "这个",
            "那个",
            "可以",
            "进行",
            "需要",
            "系统",
            "项目",
            "内容",
        }
        unique_terms: list[str] = []
        for term in raw_terms:
            normalized = str(term).strip().lower()
            if len(normalized) < 2 or normalized in stop_terms or normalized.isdigit():
                continue
            if normalized not in unique_terms:
                unique_terms.append(normalized)
        unique_terms.sort(key=lambda item: (len(item), item), reverse=True)
        for term in unique_terms:
            terms.append(term)
            if len(terms) >= 24:
                break
        return terms

    def _build_summary_coverage_supplement(self, chunks, *, max_items: int = 8) -> str:
        ordered_chunks = sorted(chunks, key=lambda item: item.chunk_index)
        if not ordered_chunks:
            return "当前记录没有可补充的正文片段。"
        selected = self._select_coverage_chunks(ordered_chunks, max_items=max_items)
        lines = []
        for index, chunk in enumerate(selected, start=1):
            lines.append(f"{index}. {self._compact_text(chunk.chunk_text, 180)}")
        return "\n".join(lines)

    def _select_coverage_chunks(self, chunks, *, max_items: int):
        if len(chunks) <= max_items:
            return chunks
        if max_items <= 1:
            return chunks[:1]
        selected = []
        seen_indexes: set[int] = set()
        for slot in range(max_items):
            index = round(slot * (len(chunks) - 1) / (max_items - 1))
            chunk = chunks[index]
            if chunk.chunk_index in seen_indexes:
                continue
            selected.append(chunk)
            seen_indexes.add(chunk.chunk_index)
        return selected

    def _build_group_summary(self, chunks) -> str:
        parts = []
        for chunk in sorted(chunks, key=lambda item: item.chunk_index):
            parts.append(f"chunk {chunk.chunk_index}: {self._compact_text(chunk.chunk_text, 160)}")
        return "；".join(parts)

    def _extract_exhaustive_items(self, question: str, chunks) -> list[str]:
        normalized = question.lower()
        if any(marker in question for marker in ["待办", "要做", "任务", "todo"]) or "todo" in normalized:
            markers = ["待办", "需要", "要", "记得", "提醒", "完成", "处理", "提交", "联系", "安排", "计划", "跟进", "todo"]
        elif any(marker in question for marker in ["风险", "风险点", "问题", "隐患"]) or "risk" in normalized:
            markers = ["风险", "可能", "担心", "问题", "阻塞", "延期", "隐患", "不确定", "失败", "超支"]
        elif any(marker in question for marker in ["付款", "支付", "款项", "金额", "付款节点"]) or "payment" in normalized:
            markers = ["付款", "支付", "尾款", "定金", "金额", "违约金", "元", "发票", "节点"]
        elif any(marker in question for marker in ["时间", "时间线", "时间点", "几点"]) or "timeline" in normalized:
            markers = ["早上", "上午", "中午", "下午", "放学", "晚上", "点", "今天", "明天", "周", "月", "日"]
        else:
            markers = []

        items: list[str] = []
        seen: set[str] = set()
        for chunk in sorted(chunks, key=lambda item: item.chunk_index):
            for sentence in self._split_context_sentences(chunk.chunk_text):
                compact = self._compact_text(sentence, 180)
                if len(compact) < 4:
                    continue
                if markers and not any(marker.lower() in compact.lower() for marker in markers):
                    continue
                if not markers and len(compact) < 8:
                    continue
                key = re.sub(r"\s+", "", compact).lower()
                if key in seen:
                    continue
                seen.add(key)
                items.append(compact)
        return items[:80]

    def _build_global_then_local_fallback(self, outline: str, expanded_chunks) -> str:
        evidence = self._snippet_from_chunks(expanded_chunks)
        if evidence:
            return f"整体来看：{outline}\n局部证据主要来自当前文件/记录中的这些片段：{evidence}"
        return f"整体来看：{outline}\n但当前文件/记录中没有检索到足够明确的局部证据。"

    def _build_selected_text_fallback(self, selected_text: str, question: str) -> str:
        compact = self._compact_text(selected_text, 360)
        if any(marker in question for marker in ["什么意思", "解释", "这段", "这句话", "这里"]):
            return f"这段话的核心意思是：{compact}"
        return f"基于你选中的文本，我能看到的内容是：{compact}"

    def _split_context_sentences(self, text: str) -> list[str]:
        normalized = (text or "").replace("\r", "\n")
        segments = re.split(r"[\n。！？!?；;]+", normalized)
        return [segment.strip(" \t，,：:") for segment in segments if segment.strip(" \t，,：:")]

    def _compact_text(self, text: str, limit: int) -> str:
        compact = " ".join((text or "").split())
        return compact if len(compact) <= limit else f"{compact[:limit].rstrip()}..."

    def _context_workflow_steps(
        self,
        *,
        route: QueryRoute,
        detail: str,
        retrieved_count: int,
        expanded_count: int,
        duration_ms: float | None = None,
    ) -> list[dict]:
        return [
            self._make_workflow_step(
                key="query_route",
                label="Query Route",
                status="done",
                detail=route.reason,
                metric=route.context_mode,
            ),
            self._make_workflow_step(
                key="context_strategy",
                label="Context Strategy",
                status="done",
                detail=detail,
                metric=route.scope,
            ),
            self._make_workflow_step(
                key="context_reader",
                label="Retriever / Reader",
                status="done",
                detail=f"Retrieved {retrieved_count} chunks and expanded/scanned {expanded_count} chunks inside the active context.",
                metric=str(expanded_count),
                duration_ms=duration_ms,
            ),
            self._make_workflow_step(
                key="context_packing",
                label="Context Packing",
                status="done",
                detail="Packed context in original source order with duplicate chunks removed.",
                metric=route.context_mode,
            ),
            self._make_workflow_step(
                key="answer_generation",
                label="Answer Generation",
                status="done",
                detail=f"Generated answer using context mode {route.context_mode}.",
                metric=f"context_{route.context_mode}",
            ),
        ]

    def _record_context_trace(
        self,
        db: Session,
        *,
        user_id: uuid.UUID,
        payload: QARequest,
        route: QueryRoute,
        active_context: ActiveContext,
        hits,
        citations: list[CitationItem],
        answer_source: str,
        effective_question: str | None,
        workflow_steps: list[dict],
        debug_metadata: dict,
    ):
        return self._record_trace(
            db,
            user_id=user_id,
            payload=payload,
            hits=hits,
            citations=citations,
            answer_source=answer_source,
            route=route,
            effective_question=effective_question,
            workflow_steps=workflow_steps,
            execution_plan=self._build_context_execution_plan(payload, route, active_context),
            extra_metadata={
                "retrieval_strategy": f"context_strategy_v1:{route.context_mode}",
                "context_strategy": route.context_mode,
                "context_scope": route.scope,
                "context_task_type": route.task_type,
                "retrieval_scope": route.retrieval_scope,
                "answer_mode": route.answer_mode,
                "router_result": context_planner_service.router_result(route),
                "active_context": active_context.as_dict(),
                "context_strategy_debug": debug_metadata,
            },
        )

    def _build_context_execution_plan(self, payload: QARequest, route: QueryRoute, active_context: ActiveContext) -> dict:
        mode_tools = {
            "local_qa": ["chunk_service(scope_filter)", "local_rerank", "neighbor_expand", "llm_answer_service"],
            "full_summary": ["memory_repository", "chunk_reader(all_chunks)", "map_reduce_summary", "coverage_check"],
            "exhaustive_extract": ["chunk_reader(all_chunks)", "per_chunk_extract", "merge_dedupe"],
            "global_then_local": ["memory_summary", "chunk_service(scope_filter)", "neighbor_expand", "llm_answer_service"],
            "direct_selected_text": ["selected_text", "visible_neighbor_chunks", "llm_answer_service"],
        }
        return {
            "planner_version": "context_strategy_v1",
            "summary": f"Use {route.context_mode} for {route.scope}; ordinary global RAG is bypassed for this active-context question.",
            "route": route.route,
            "intent": route.intent,
            "mode": payload.mode,
            "scope": route.scope,
            "task_type": route.task_type,
            "context_mode": route.context_mode,
            "needs_full_coverage": route.needs_full_coverage,
            "needs_exact_evidence": route.needs_exact_evidence,
            "retrieval_scope": route.retrieval_scope,
            "answer_mode": route.answer_mode,
            "active_context": active_context.as_dict(),
            "subquestions": [
                self._planned_subquestion(
                    question=payload.question,
                    tool="context_planner",
                    reason=f"Plan context mode {route.context_mode} before retrieval or reading.",
                )
            ],
            "tools": mode_tools.get(route.context_mode, ["context_planner", "llm_answer_service"]),
            "context_packing": {
                "strategy": route.context_mode,
                "scope_filter": route.scope,
                "global_retrieval_allowed": route.scope == "global",
            },
        }

    def _log_context_strategy_debug(self, debug_metadata: dict) -> None:
        logger.info(
            "context_strategy_debug user_query=%r active_context=%s router_result=%s context_mode=%s "
            "retrieved_chunk_ids=%s expanded_chunk_ids=%s final_context_token_count=%s "
            "llm_input_content_length=%s triggered_full_summary=%s triggered_exhaustive_extract=%s",
            debug_metadata.get("user_query"),
            debug_metadata.get("active_context"),
            debug_metadata.get("router_result"),
            debug_metadata.get("context_mode"),
            debug_metadata.get("retrieved_chunk_ids"),
            debug_metadata.get("expanded_chunk_ids"),
            debug_metadata.get("final_context_token_count"),
            debug_metadata.get("llm_input_content_length"),
            debug_metadata.get("triggered_full_summary"),
            debug_metadata.get("triggered_exhaustive_extract"),
        )

    def _attach_llm_debug_metadata(self, debug_metadata: dict, llm_result: LLMAnswerResult) -> None:
        debug_metadata["llm_status"] = llm_result.status
        debug_metadata["llm_available"] = llm_result.status not in {"unavailable", "skipped"}
        debug_metadata["llm_answered"] = llm_result.ok
        debug_metadata["llm_reason"] = llm_result.reason

    def _content_is_attachment_only(self, content: str) -> bool:
        compact = content.strip()
        if not compact:
            return True
        lines = [line.strip() for line in compact.splitlines() if line.strip()]
        return bool(lines) and all(line.startswith("附件：") for line in lines)

    def _build_local_context_answer(self, title: str, content: str, question: str) -> str:
        compact = " ".join(content.split())
        if not compact:
            return f"这条记录《{title}》目前没有可总结的正文内容。"

        normalized_question = question.strip().lower()
        sentences = [segment.strip() for segment in content.replace("\r", "\n").replace("。", "。\n").splitlines() if segment.strip()]
        headline = "；".join(sentences[:3]) if sentences else compact[:180].rstrip()

        if any(marker in normalized_question for marker in ["缩短", "简短", "精简", "一句话", "shorter", "shorten"]):
            shortened = headline[:120].rstrip("；，、 ")
            return f"简短说，这条记录主要在讲：{shortened}。"

        if any(marker in normalized_question for marker in ["总结", "概括", "讲讲", "看看", "主要", "干了啥", "做了什么", "说了什么"]):
            key_points = [segment.rstrip("。") for segment in self._select_coverage_sentences(sentences, max_items=8)]
            if key_points:
                summary = "；".join(key_points)
                return f"这条记录主要在讲：{summary}。"
            return f"这条记录主要在讲：{headline}。"

        excerpt = compact[:320].rstrip()
        return f"我目前从《{title}》里能直接看到的信息是：{excerpt}{'...' if len(compact) > len(excerpt) else ''}"

    def _build_transform_fallback(self, intent: str, title: str, content: str, chunks) -> str:
        sentences = [segment.strip() for segment in content.replace("\r", "\n").replace("。", "。\n").splitlines() if segment.strip()]
        key_points = self._select_coverage_sentences(sentences, max_items=6) if sentences else []
        if intent == "doc_rewrite_weekly_report":
            lines = [f"- {item.rstrip('。')}" for item in key_points[:5]] or [f"- {self._compact_text(content, 120)}"]
            return "\n".join(
                [
                    f"{title} 周报整理",
                    "",
                    "本周进展：",
                    *lines,
                ]
            )
        if intent == "doc_rewrite_email":
            summary = "；".join(item.rstrip("。") for item in key_points[:4]) or self._compact_text(content, 180)
            return f"你好，\n\n我把《{title}》整理成邮件说明如下：{summary}。\n\n如需我继续改成更正式或更简短的版本，可以继续说明。"
        if intent == "doc_translate":
            summary = "；".join(item.rstrip("。") for item in key_points[:4]) or self._compact_text(content, 180)
            return f"当前还没有可用的翻译模型配置。我先提炼出原文重点：{summary}。"
        summary = "；".join(item.rstrip("。") for item in key_points[:5]) or self._compact_text(content, 200)
        return f"我先按你的要求把《{title}》重写成更简洁的版本：{summary}。"

    def _build_direct_response(self, question: str, route: QueryRoute) -> QAResponseData:
        del route
        normalized = question.strip().lower()
        if any(marker in normalized for marker in ["你是谁", "who are you"]):
            answer = "我是你的 AI 助手，可以帮你理解当前记录、整理内容、回答一般问题，也可以在需要时结合你的个人记忆来回答。"
            followups = ["你能做什么", "帮我总结当前记录", "帮我整理今天的待办"]
        elif any(marker in normalized for marker in ["你能做什么", "what can you do", "你会什么"]):
            answer = "我可以做三类事：一是读你当前打开的记录并做总结、提取、改写；二是结合你的个人记忆回答问题；三是在启用工具时处理天气或联网查询这类外部问题。"
            followups = ["帮我总结当前记录", "我最近有哪些重要事情", "北京天气怎么样"]
        else:
            answer = "这个问题我会按普通对话来处理，不会默认绑定到当前记录。你也可以直接告诉我，是想聊一般问题，还是想让我只看当前文档。"
            followups = ["只看当前记录总结一下", "不要参考当前记录", "你能做什么"]

        return QAResponseData(answer=answer, citations=[], suggested_followups=followups)

    def _build_clarification_response(self, question: str, route: QueryRoute) -> QAResponseData:
        del question, route
        return QAResponseData(
            answer="你是想让我只看当前这条记录/文档，还是按一般问题来回答？",
            citations=[],
            suggested_followups=["只看当前记录", "按一般问题回答", "联网查一下"],
        )

    def _finalize_simple_route_response(
        self,
        db: Session,
        user_id: uuid.UUID,
        payload: QARequest,
        route: QueryRoute,
        *,
        effective_question: str | None,
        response: QAResponseData,
        answer_source: str,
    ) -> QAResponseData:
        workflow_steps = [
            self._make_workflow_step(
                key="query_route",
                label="Query Route",
                status="done",
                detail=route.reason,
                metric=route.intent,
            )
        ]
        if effective_question and effective_question != payload.question:
            workflow_steps.append(
                self._make_workflow_step(
                    key="followup_rewrite",
                    label="Follow-up Rewrite",
                    status="done",
                    detail="Rewrote the follow-up into a retrieval-ready question using recent conversation context.",
                    metric="context_used",
                )
            )
        workflow_steps.append(
            self._make_workflow_step(
                key="answer_generation",
                label="Answer Generation",
                status="done",
                detail=self._workflow_answer_detail(answer_source, len(response.citations)),
                metric=answer_source,
            )
        )
        response.trace = self._record_trace(
            db,
            user_id=user_id,
            payload=payload,
            hits=[],
            citations=response.citations,
            answer_source=answer_source,
            route=route,
            effective_question=effective_question,
            workflow_steps=workflow_steps,
            execution_plan=self._build_execution_plan(
                original_question=payload.question,
                effective_question=effective_question or payload.question,
                mode=payload.mode,
                route=route,
            ),
        )
        return response

    def _select_coverage_sentences(self, sentences: list[str], *, max_items: int) -> list[str]:
        cleaned = [sentence.strip(" 。；;\n\t") for sentence in sentences if sentence.strip(" 。；;\n\t")]
        if len(cleaned) <= max_items:
            return cleaned
        if max_items <= 1:
            return cleaned[:1]

        selected: list[str] = []
        selected_indexes: set[int] = set()
        for slot in range(max_items):
            index = round(slot * (len(cleaned) - 1) / (max_items - 1))
            if index in selected_indexes:
                continue
            selected_indexes.add(index)
            selected.append(cleaned[index])
        return selected

    def _answer_fact_question(
        self,
        db: Session,
        user_id: uuid.UUID,
        payload: QARequest,
        hits,
        citations: list[CitationItem],
        route: QueryRoute,
        *,
        trace_payload: QARequest | None = None,
        workflow_steps: list[dict] | None = None,
        execution_plan: dict | None = None,
    ) -> QAResponseData | None:
        fact_insight, fact_duration_ms = self._timed_call(lambda: fact_insight_service.answer_question(db, user_id, payload.question))
        if fact_insight is None:
            return None
        answer = self._merge_mode_notice(self._build_mode_notice(payload.mode, route), fact_insight.answer)
        trace_citations = fact_insight.citations or citations
        active_steps = list(workflow_steps or [])
        active_steps.append(
            self._make_workflow_step(
                key="answer_generation",
                label="Answer Generation",
                status="done",
                detail=self._workflow_answer_detail("fact_insight", len(trace_citations)),
                metric="fact_insight",
                duration_ms=fact_duration_ms,
            )
        )
        trace = self._record_trace(
            db,
            user_id=user_id,
            payload=trace_payload or payload,
            hits=hits,
            citations=trace_citations,
            answer_source="fact_insight",
            route=route,
            effective_question=payload.question,
            workflow_steps=active_steps,
            execution_plan=execution_plan,
        )
        return QAResponseData(
            answer=answer,
            citations=trace_citations,
            suggested_followups=fact_insight.suggested_followups,
            trace=trace,
        )

    def _answer_insight_question(self, db: Session, user_id: uuid.UUID, question: str) -> QAResponseData | None:
        insights = dashboard_service.get_insights(db, user_id).cards
        if not insights:
            return None

        lowered = question.lower()
        selected = insights
        if any(marker in lowered for marker in ["expense", "消费", "开销", "花钱"]):
            selected = [card for card in insights if card.kind == "expense"] or selected
        elif any(marker in lowered for marker in ["mood", "情绪", "睡眠", "压力"]):
            selected = [card for card in insights if card.kind == "mood"] or selected
        elif any(marker in lowered for marker in ["learning", "研究", "学习", "技术"]):
            selected = [card for card in insights if card.kind == "learning"] or selected
        elif any(marker in lowered for marker in ["plan", "待办", "计划", "安排"]):
            selected = [card for card in insights if card.kind == "plan"] or selected
        elif any(marker in lowered for marker in ["project", "项目", "进展", "里程碑", "阻塞"]):
            selected = [card for card in insights if card.kind == "project"] or selected

        cards = selected[:2]
        answer_sections = []
        for card in cards:
            if card.kind == "project":
                bullet_like = "\n".join(f"- {item}" for item in card.items[:4]) if card.items else ""
                answer_sections.append(f"{card.title}：{card.value}\n{card.detail}" + (f"\n{bullet_like}" if bullet_like else ""))
                continue
            answer_sections.append(
                f"{card.title}：{card.value}\n{card.detail}\n" + ("；".join(card.items[:3]) if card.items else "")
            )
        citations = self._build_insight_citations(cards)
        followups = [card.question for card in cards if card.question][:3]
        return QAResponseData(
            answer="\n\n".join(answer_sections),
            citations=citations,
            suggested_followups=followups,
            trace=None,
        )

    def _build_insight_citations(self, cards) -> list[CitationItem]:
        citations: list[CitationItem] = []
        seen: set[tuple[str, str]] = set()
        for card in cards:
            for source in card.sources[:3]:
                key = (source.type, source.id)
                if key in seen:
                    continue
                seen.add(key)
                citations.append(
                    CitationItem(
                        type=source.type,
                        id=source.id,
                        title=source.title,
                        snippet=source.snippet,
                        score=0.9,
                    )
                )
        if citations:
            return citations[:4]
        return [
            CitationItem(
                type="insight",
                id=card.kind,
                title=card.title,
                snippet=f"{card.value} - {card.detail}",
                score=0.9,
            )
            for card in cards
        ]

    def _build_effective_question(self, payload: QARequest) -> str:
        question = payload.question.strip()
        if not question or not payload.conversation_context:
            return question
        if not self._looks_like_followup(question):
            return question

        context_lines = []
        for message in payload.conversation_context[-4:]:
            content = " ".join(message.content.strip().split())
            if not content:
                continue
            role = "用户" if message.role == "user" else "助手"
            context_lines.append(f"{role}：{content[:180]}")
        if not context_lines:
            return question
        return "；".join([*context_lines, f"当前追问：{question}"])

    def _looks_like_followup(self, question: str) -> bool:
        normalized = question.strip().lower()
        followup_markers = [
            "那",
            "它",
            "这个",
            "这些",
            "上述",
            "上面",
            "刚才",
            "继续",
            "展开",
            "具体",
            "分别",
            "还有呢",
            "why",
            "how about",
            "what about",
            "those",
            "that",
            "it",
        ]
        if not any(marker in normalized for marker in followup_markers):
            return False
        return len(normalized) <= 32 or any(marker in normalized for marker in ["上面", "上述", "刚才", "前面", "继续", "展开", "具体"])

    def _select_memories(self, memories, hits):
        selected_memories = []
        seen_memory_ids = set()
        for hit in hits:
            if hit.memory.id in seen_memory_ids:
                continue
            selected_memories.append(hit.memory)
            seen_memory_ids.add(hit.memory.id)
        if not selected_memories and memories:
            selected_memories = memories[:3]
        return selected_memories

    def _build_memory_citations(self, selected_memories, hits) -> list[CitationItem]:
        citations = [
            CitationItem(
                type="memory",
                id=str(hit.memory.id),
                title=hit.memory.title or "Untitled Memory",
                snippet=hit.chunk.chunk_summary or hit.memory.content_summary or "",
                score=hit.score,
            )
            for hit in hits[:DIRECT_CITATION_WINDOW]
        ]
        if citations:
            return citations
        return [
            CitationItem(
                type="memory",
                id=str(memory.id),
                title=memory.title or "Untitled Memory",
                snippet=memory.content_summary or "",
                score=0.5,
            )
            for memory in selected_memories[:3]
        ]

    def _expand_related_memories(self, db: Session, user_id: uuid.UUID, memories, *, limit: int = 4) -> list[dict]:
        expanded: list[dict] = []
        if not memories:
            return expanded
        # Only exclude the anchor/source memory itself. A related memory may also
        # appear as a lower-ranked direct hit, and we still want relation expansion
        # to surface that connection for reranking and trace observability.
        seen_memory_ids = {memories[0].id}
        allowed_relation_types = {"shared_fact", "shared_entity", "shared_semantic_signal"}
        for source_memory in memories[:1]:
            related_items = memory_relation_service.list_related(db, user_id, str(source_memory.id), limit=limit)
            for item in related_items:
                if item.relation_type not in allowed_relation_types or float(item.score) < 0.48:
                    continue
                related_id = uuid.UUID(item.id)
                if related_id in seen_memory_ids:
                    continue
                related_memory = memory_repository.get_for_user(db, user_id, related_id)
                if related_memory is None:
                    continue
                seen_memory_ids.add(related_id)
                expanded.append(
                    {
                        "source_memory_id": str(source_memory.id),
                        "source_memory_title": source_memory.title or "Untitled Memory",
                        "memory": related_memory,
                        "relation_type": item.relation_type,
                        "relation_reason": item.relation_reason,
                        "relation_score": item.score,
                    }
                )
                if len(expanded) >= limit:
                    return expanded
        return expanded

    def _rerank_memory_citations(
        self,
        db: Session,
        user_id: uuid.UUID,
        question: str,
        citations: list[CitationItem],
        hits,
        related_memories: list[dict],
        *,
        limit: int = 5,
    ) -> tuple[list[CitationItem], list[dict]]:
        candidates: dict[str, dict] = {}
        direct_hit_meta_by_memory: dict[str, dict] = {}
        hit_scores = [float(hit.score) for hit in hits] or [1.0]
        max_hit_score = max(max(hit_scores), 1e-6)
        for rank, hit in enumerate(hits, start=1):
            memory_id = str(hit.memory.id)
            if memory_id in direct_hit_meta_by_memory:
                continue
            direct_hit_meta_by_memory[memory_id] = {
                "rank": rank,
                "raw_score": round(float(hit.score), 4),
                "normalized_score": round(float(hit.score) / max_hit_score, 4),
                "title": hit.memory.title or "Untitled Memory",
                "category": hit.memory.category,
                "snippet": hit.chunk.chunk_summary or hit.memory.content_summary or hit.chunk.chunk_text[:160],
            }

        for citation in citations:
            if citation.type != "memory":
                candidates[citation.id] = {
                    "citation": citation,
                    "direct_score": float(citation.score),
                    "relation_score": 0.0,
                    "source": "external",
                    "explanation": {
                        "memory_id": citation.id,
                        "title": citation.title,
                        "source": "external",
                        "direct_score": round(float(citation.score), 4),
                        "relation_score": 0.0,
                        "recency_score": 0.0,
                        "fact_score": 0.0,
                        "source_bonus": 0.0,
                        "final_score": round(float(citation.score), 4),
                        "relation_reason": "",
                        "score_formula": "external_source",
                        "selected": True,
                        "exclusion_reason": "",
                        "exclusion_reason_detail": "",
                        "snippet": citation.snippet,
                    },
                }
                continue
            normalized_direct_score = float(citation.score) / max_hit_score
            if normalized_direct_score < MIN_DIRECT_SCORE:
                continue
            candidates[citation.id] = {
                "citation": citation,
                "direct_score": normalized_direct_score,
                "relation_score": 0.0,
                "source": "direct",
                "explanation": {
                    "memory_id": citation.id,
                    "title": citation.title,
                    "source": "direct",
                    "direct_score": round(normalized_direct_score, 4),
                    "raw_hit_score": direct_hit_meta_by_memory.get(citation.id, {}).get("raw_score"),
                    "direct_hit_rank": direct_hit_meta_by_memory.get(citation.id, {}).get("rank"),
                    "relation_score": 0.0,
                    "recency_score": 0.0,
                    "fact_score": 0.0,
                    "source_bonus": 0.0,
                    "final_score": 0.0,
                    "relation_reason": "",
                    "score_formula": "direct*0.56 + relation*0.26 + recency*0.08 + fact*0.10",
                    "selected": False,
                    "exclusion_reason": "",
                    "exclusion_reason_detail": "",
                    "snippet": citation.snippet,
                },
            }

        for item in related_memories:
            memory = item["memory"]
            memory_id = str(memory.id)
            reason = item["relation_reason"]
            snippet = memory.content_summary or memory.content_clean or memory.content_raw[:160]
            existing = candidates.get(memory_id)
            relation_score = max(0.0, min(float(item["relation_score"]), 1.0))
            if existing is not None:
                existing["relation_score"] = max(float(existing["relation_score"]), relation_score)
                existing["explanation"]["relation_score"] = round(max(float(existing["explanation"]["relation_score"]), relation_score), 4)
                if reason:
                    existing["explanation"]["relation_reason"] = reason
                continue
            candidates[memory_id] = {
                "citation": CitationItem(
                    type="memory",
                    id=memory_id,
                    title=memory.title or "Untitled Memory",
                    snippet=f"{reason}. {snippet}" if reason else snippet,
                    score=relation_score,
                ),
                "direct_score": 0.0,
                "relation_score": relation_score,
                "source": "relation",
                "explanation": {
                    "memory_id": memory_id,
                    "title": memory.title or "Untitled Memory",
                    "source": "relation",
                    "direct_score": 0.0,
                    "raw_hit_score": direct_hit_meta_by_memory.get(memory_id, {}).get("raw_score"),
                    "direct_hit_rank": direct_hit_meta_by_memory.get(memory_id, {}).get("rank"),
                    "relation_score": round(relation_score, 4),
                    "recency_score": 0.0,
                    "fact_score": 0.0,
                    "source_bonus": 0.04,
                    "final_score": 0.0,
                    "relation_reason": reason,
                    "score_formula": "direct*0.56 + relation*0.26 + recency*0.08 + fact*0.10 + relation_bonus",
                    "selected": False,
                    "exclusion_reason": "",
                    "exclusion_reason_detail": "",
                    "snippet": snippet,
                },
            }

        memory_ids = [uuid.UUID(memory_id) for memory_id in candidates if self._is_uuid(memory_id)]
        memory_by_id = {
            str(memory.id): memory
            for memory in (memory_repository.get_for_user(db, user_id, memory_id) for memory_id in memory_ids)
            if memory is not None
        }
        fact_confidence = self._fact_confidence_by_memory(db, user_id, memory_ids)

        reranked: list[tuple[float, CitationItem]] = []
        scored_breakdowns: list[dict] = []
        rejected_breakdowns: list[dict] = []
        for memory_id, item in candidates.items():
            citation = item["citation"]
            memory = memory_by_id.get(memory_id)
            recency_score = self._recency_score(memory.event_time if memory is not None else None)
            fact_score = fact_confidence.get(memory_id, 0.0)
            direct_score = min(float(item["direct_score"]), 1.0)
            relation_score = min(float(item["relation_score"]), 1.0)
            source_bonus = 0.04 if item["source"] == "relation" else 0.0
            final_score = (
                direct_score * 0.56
                + relation_score * 0.26
                + recency_score * 0.08
                + fact_score * 0.1
            )
            final_score += source_bonus
            explanation = item["explanation"]
            explanation["recency_score"] = round(recency_score, 4)
            explanation["fact_score"] = round(fact_score, 4)
            explanation["source_bonus"] = round(source_bonus, 4)
            explanation["final_score"] = round(final_score, 4)
            if memory is not None:
                explanation["event_time"] = memory.event_time.isoformat() if memory.event_time else None
                explanation["category"] = memory.category
            if final_score < FINAL_CITATION_SCORE_FLOOR:
                explanation["selected"] = False
                explanation["exclusion_reason"] = "below_final_score_floor"
                explanation["exclusion_reason_detail"] = f"综合分 {final_score:.2f} 低于保留阈值 {FINAL_CITATION_SCORE_FLOOR:.2f}。"
                rejected_breakdowns.append(explanation)
                continue
            scored_breakdowns.append(explanation)
            reranked.append(
                (
                    final_score,
                    CitationItem(
                        type=citation.type,
                        id=citation.id,
                        title=citation.title,
                        snippet=citation.snippet,
                        score=round(final_score, 4),
                    ),
                )
            )

        reranked.sort(key=lambda pair: pair[0], reverse=True)
        scored_breakdowns.sort(key=lambda item: float(item["final_score"]), reverse=True)
        selected_memory_ids: set[str] = set()
        anchor_citation = next((citation for _, citation in reranked if citation.title.lower() in question.lower()), None)
        if not related_memories and anchor_citation is not None:
            top_citation = anchor_citation
            selected_memory_ids = {top_citation.id}
            for item in scored_breakdowns:
                if item.get("memory_id") == top_citation.id:
                    item["selected"] = True
                    item["exclusion_reason"] = ""
                    item["exclusion_reason_detail"] = ""
                else:
                    item["selected"] = False
                    item["exclusion_reason"] = "anchor_only_shortcut"
                    item["exclusion_reason_detail"] = "问题几乎直接指向锚点记忆，系统只保留最确定的一条引用。"
                    rejected_breakdowns.append(item)
            all_breakdowns = self._finalize_breakdowns(
                direct_hit_meta_by_memory=direct_hit_meta_by_memory,
                candidate_memory_ids=set(candidates.keys()),
                selected_memory_ids=selected_memory_ids,
                selected_breakdowns=[item for item in scored_breakdowns if item.get("memory_id") == top_citation.id],
                rejected_breakdowns=rejected_breakdowns,
            )
            return [top_citation], all_breakdowns

        selected_citations = [citation for _, citation in reranked[:limit]]
        selected_memory_ids = {citation.id for citation in selected_citations if citation.type == "memory"}
        selected_breakdowns: list[dict] = []
        for item in scored_breakdowns:
            if item.get("memory_id") in selected_memory_ids:
                item["selected"] = True
                item["exclusion_reason"] = ""
                item["exclusion_reason_detail"] = ""
                selected_breakdowns.append(item)
            else:
                item["selected"] = False
                item["exclusion_reason"] = "trimmed_after_rerank"
                item["exclusion_reason_detail"] = f"综合分足够，但最终只保留前 {limit} 条引用。"
                rejected_breakdowns.append(item)

        all_breakdowns = self._finalize_breakdowns(
            direct_hit_meta_by_memory=direct_hit_meta_by_memory,
            candidate_memory_ids=set(candidates.keys()),
            selected_memory_ids=selected_memory_ids,
            selected_breakdowns=selected_breakdowns,
            rejected_breakdowns=rejected_breakdowns,
        )
        return selected_citations, all_breakdowns

    def _fact_confidence_by_memory(self, db: Session, user_id: uuid.UUID, memory_ids: list[uuid.UUID]) -> dict[str, float]:
        memory_id_set = set(memory_ids)
        if not memory_id_set:
            return {}
        confidence: dict[str, float] = {}
        for fact in fact_repository.list_for_user(db, user_id):
            if fact.memory_id not in memory_id_set:
                continue
            key = str(fact.memory_id)
            confidence[key] = max(confidence.get(key, 0.0), float(fact.confidence_score))
        return confidence

    def _recency_score(self, event_time: datetime | None) -> float:
        if event_time is None:
            return 0.0
        now = datetime.now(timezone.utc)
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
        days = max((now - event_time).total_seconds() / 86400, 0.0)
        return exp(-days / 30)

    def _is_uuid(self, value: str) -> bool:
        try:
            uuid.UUID(value)
            return True
        except ValueError:
            return False

    def _build_memory_answer(self, db: Session, user_id: uuid.UUID, payload: QARequest, memories, hits, citations, related_memories=None) -> str:
        route = query_router_service.route(payload.question, payload.mode)
        mode_notice = self._build_mode_notice(payload.mode, route)
        if not memories:
            return self._merge_mode_notice(mode_notice, "\u5f53\u524d\u8fd8\u6ca1\u6709\u8db3\u591f\u7684\u8bb0\u5f55\u53ef\u4f9b\u56de\u7b54\uff0c\u5efa\u8bae\u5148\u8bb0\u4e0b\u4e00\u4e9b\u9879\u76ee\u3001\u5b66\u4e60\u6216\u5f85\u529e\u4fe1\u606f\u3002")

        user_settings = settings_service.get_settings(db, user_id)
        llm_answer = llm_answer_service.generate_grounded_answer(
            question=payload.question,
            provider=user_settings.llm_provider,
            model=user_settings.llm_model,
            context_blocks=self._build_context_blocks(memories, hits, citations, related_memories or []),
            answer_mode=route.answer_mode,
        )
        if llm_answer:
            return self._merge_mode_notice(mode_notice, llm_answer)

        titles = "\u3001".join([(memory.title or "\u672a\u547d\u540d\u8bb0\u5f55") for memory in memories[:2]])
        basis = "\uff1b".join([hit.chunk.chunk_summary or "" for hit in hits[:2] if hit.chunk.chunk_summary])
        if "\u6700\u8fd1" in payload.question:
            if basis:
                return self._merge_mode_notice(mode_notice, f"\u6700\u8fd1\u6700\u503c\u5f97\u5173\u6ce8\u7684\u5185\u5bb9\u4e3b\u8981\u96c6\u4e2d\u5728\uff1a{titles}\u3002\u53c2\u8003\u5230\u7684\u5173\u952e\u7247\u6bb5\u5305\u62ec\uff1a{basis}")
            return self._merge_mode_notice(mode_notice, f"\u6700\u8fd1\u6700\u503c\u5f97\u5173\u6ce8\u7684\u5185\u5bb9\u4e3b\u8981\u96c6\u4e2d\u5728\uff1a{titles}\u3002")
        if basis:
            return self._merge_mode_notice(mode_notice, f"\u6211\u4ece\u4f60\u7684\u957f\u671f\u8bb0\u5fc6\u91cc\u627e\u5230\u4e86\u8fd9\u4e9b\u76f8\u5173\u5185\u5bb9\uff1a{titles}\u3002\u5173\u952e\u7247\u6bb5\u5305\u62ec\uff1a{basis}")
        return self._merge_mode_notice(mode_notice, f"\u6211\u4ece\u4f60\u7684\u957f\u671f\u8bb0\u5fc6\u91cc\u627e\u5230\u4e86\u8fd9\u4e9b\u76f8\u5173\u5185\u5bb9\uff1a{titles}\u3002")

    def _answer_weather_question(self, question: str, memory_citations: list[CitationItem]) -> QAResponseData | None:
        location = self._extract_weather_location(question)
        if not location:
            return QAResponseData(
                answer="\u4f60\u60f3\u67e5\u54ea\u91cc\u7684\u5929\u6c14\uff1f\u53ef\u4ee5\u76f4\u63a5\u95ee\u6211\u201c\u5317\u4eac\u5929\u6c14\u600e\u4e48\u6837\u201d\u6216\u201cSan Francisco weather\u201d\u3002",
                citations=memory_citations,
                suggested_followups=["\u5317\u4eac\u5929\u6c14\u600e\u4e48\u6837\uff1f", "\u4e0a\u6d77\u5929\u6c14\u600e\u4e48\u6837\uff1f", "San Francisco weather"],
            )
        try:
            weather = weather_service.current_weather(location)
        except RuntimeError as exc:
            return QAResponseData(
                answer=f"\u5929\u6c14\u67e5\u8be2\u6682\u65f6\u5931\u8d25\uff1a{exc}",
                citations=memory_citations,
                suggested_followups=["\u5317\u4eac\u5929\u6c14\u600e\u4e48\u6837\uff1f", "\u4e0a\u6d77\u5929\u6c14\u600e\u4e48\u6837\uff1f"],
            )
        if not weather.configured:
            return None

        temp = f"{weather.temperature_c:g}\u00b0C" if weather.temperature_c is not None else "\u6e29\u5ea6\u6682\u7f3a"
        feels = f"\uff0c\u4f53\u611f {weather.feels_like_c:g}\u00b0C" if weather.feels_like_c is not None else ""
        humidity = f"\uff0c\u6e7f\u5ea6 {weather.humidity}%" if weather.humidity is not None else ""
        wind = f"\uff0c\u98ce\u901f {weather.wind_speed_mps:g} m/s" if weather.wind_speed_mps is not None else ""
        answer = f"{weather.location} \u5f53\u524d\u5929\u6c14\uff1a{weather.description}\uff0c{temp}{feels}{humidity}{wind}\u3002"
        citations = [
            CitationItem(
                type="weather",
                id=f"openweather:{weather.location}",
                title=f"OpenWeather · {weather.location}",
                snippet=answer,
                score=1.0,
            )
        ]
        return QAResponseData(
            answer=answer,
            citations=citations,
            suggested_followups=["\u4eca\u5929\u9002\u5408\u51fa\u95e8\u5417\uff1f", "\u5e2e\u6211\u67e5\u4e00\u4e0b\u660e\u5929\u7684\u5929\u6c14", "\u7ed3\u5408\u6211\u7684\u5f85\u529e\u770b\u770b\u4eca\u5929\u5b89\u6392"],
        )

    def _answer_web_question(self, question: str, memory_citations: list[CitationItem]) -> QAResponseData | None:
        try:
            search = web_search_service.search(question, max_results=5)
        except RuntimeError as exc:
            return QAResponseData(
                answer=f"\u8054\u7f51\u67e5\u8be2\u6682\u65f6\u5931\u8d25\uff1a{exc}",
                citations=memory_citations,
                suggested_followups=["\u53ea\u6839\u636e\u6211\u7684\u8bb0\u5f55\u56de\u7b54", "\u6362\u4e00\u4e2a\u66f4\u5177\u4f53\u7684\u95ee\u9898\u8bd5\u8bd5"],
            )
        if not search.configured:
            return None

        web_citations = [
            CitationItem(
                type="web",
                id=result.url,
                title=result.title,
                snippet=result.content[:220],
                score=result.score if result.score is not None else 0.75,
            )
            for result in search.results[:3]
        ]
        if search.answer:
            answer = f"\u8054\u7f51\u67e5\u8be2\u7ed3\u679c\uff1a{search.answer}"
        elif search.results:
            bullets = "\uff1b".join(f"{result.title}: {result.content[:90]}" for result in search.results[:3])
            answer = f"\u8054\u7f51\u67e5\u8be2\u627e\u5230\u4e86\u8fd9\u4e9b\u4fe1\u606f\uff1a{bullets}"
        else:
            answer = "\u8054\u7f51\u67e5\u8be2\u6ca1\u6709\u627e\u5230\u8db3\u591f\u53ef\u9760\u7684\u7ed3\u679c\u3002"
        if memory_citations:
            answer = f"{answer}\n\n\u6211\u4e5f\u4fdd\u7559\u4e86\u4e0e\u4f60\u4e2a\u4eba\u8bb0\u5fc6\u76f8\u5173\u7684\u5f15\u7528\uff0c\u65b9\u4fbf\u4f60\u628a\u5916\u90e8\u4fe1\u606f\u548c\u81ea\u5df1\u7684\u8bb0\u5f55\u5bf9\u7167\u3002"
        return QAResponseData(
            answer=answer,
            citations=web_citations + memory_citations[:2],
            suggested_followups=["\u628a\u8fd9\u4e9b\u7ed3\u679c\u548c\u6211\u7684\u8bb0\u5f55\u5bf9\u6bd4\u4e00\u4e0b", "\u53ea\u603b\u7ed3\u6700\u53ef\u4fe1\u7684\u6765\u6e90", "\u7ee7\u7eed\u67e5\u66f4\u5177\u4f53\u7684\u4fe1\u606f"],
        )

    def _build_context_blocks(self, memories, hits, citations, related_memories=None) -> list[str]:
        contexts: list[str] = []
        seen_memory_ids = set()
        for hit in hits[:5]:
            if hit.memory.id in seen_memory_ids:
                continue
            seen_memory_ids.add(hit.memory.id)
            contexts.append(
                "\n".join(
                    [
                        f"\u6807\u9898\uff1a{hit.memory.title or '\u672a\u547d\u540d\u8bb0\u5f55'}",
                        f"\u5206\u7c7b\uff1a{hit.memory.category}",
                        f"\u6458\u8981\uff1a{hit.memory.content_summary or hit.chunk.chunk_summary or '\u65e0'}",
                        f"\u547d\u4e2d\u7247\u6bb5\uff1a{hit.chunk.chunk_summary or hit.chunk.chunk_text}",
                    ]
                )
            )
        if contexts:
            for item in (related_memories or [])[:4]:
                memory = item["memory"]
                if memory.id in seen_memory_ids:
                    continue
                seen_memory_ids.add(memory.id)
                contexts.append(
                    "\n".join(
                        [
                            "\u5173\u8054\u8bb0\u5fc6\uff1a\u662f",
                            f"\u5173\u8054\u539f\u56e0\uff1a{item['relation_reason']}",
                            f"\u6807\u9898\uff1a{memory.title or '\u672a\u547d\u540d\u8bb0\u5f55'}",
                            f"\u5206\u7c7b\uff1a{memory.category}",
                            f"\u6458\u8981\uff1a{memory.content_summary or memory.content_clean or '\u65e0'}",
                        ]
                    )
                )
            return contexts
        for memory, citation in zip(memories[:3], citations[:3], strict=False):
            contexts.append(
                "\n".join(
                    [
                        f"\u6807\u9898\uff1a{memory.title or '\u672a\u547d\u540d\u8bb0\u5f55'}",
                        f"\u5206\u7c7b\uff1a{memory.category}",
                        f"\u6458\u8981\uff1a{citation.snippet or memory.content_summary or '\u65e0'}",
                    ]
                )
            )
        return contexts

    def _build_mode_notice(self, mode: str, route: QueryRoute) -> str:
        if mode == "hybrid_web" and route.route in {"weather", "web"}:
            return "\u8054\u7f51\u8865\u5145\u5df2\u5f00\u542f\uff1a\u6211\u4f1a\u4f18\u5148\u4f7f\u7528\u5df2\u914d\u7f6e\u7684\u5916\u90e8\u5de5\u5177\uff0c\u5e76\u4fdd\u7559\u53ef\u8ffd\u6eaf\u6765\u6e90\u3002"
        if mode == "hybrid_web" and route.route == "fact":
            return "\u8fd9\u4e2a\u95ee\u9898\u66f4\u9002\u5408\u5148\u6839\u636e\u4f60\u7684\u7ed3\u6784\u5316\u8bb0\u5fc6\u56de\u7b54\uff0c\u6211\u6ca1\u6709\u628a\u5b83\u4ea4\u7ed9\u5916\u7f51\u731c\u6d4b\u3002"
        return ""

    def _merge_mode_notice(self, notice: str, answer: str) -> str:
        if not notice:
            return answer
        return f"{notice}\n\n{answer}"

    def _extract_weather_location(self, question: str) -> str:
        known_locations = [
            "San Francisco",
            "New York",
            "Los Angeles",
            "Seattle",
            "\u5317\u4eac",
            "\u4e0a\u6d77",
            "\u6df1\u5733",
            "\u5e7f\u5dde",
            "\u676d\u5dde",
            "\u6210\u90fd",
            "\u6b66\u6c49",
            "\u5357\u4eac",
            "\u91cd\u5e86",
            "\u5929\u6d25",
            "\u82cf\u5dde",
        ]
        for location in known_locations:
            if location.lower() in question.lower():
                return location
        cleaned = question.strip()
        for token in ["\u5929\u6c14\u600e\u4e48\u6837", "\u5929\u6c14\u5982\u4f55", "\u5929\u6c14", "\u6c14\u6e29", "\u4f1a\u4e0b\u96e8\u5417", "\u4e0b\u96e8\u5417", "weather", "temperature", "\u600e\u4e48\u6837", "\u5982\u4f55", "\uff1f", "?"]:
            cleaned = cleaned.replace(token, " ")
        return " ".join(cleaned.split())

    def _record_trace(
        self,
        db: Session,
        *,
        user_id: uuid.UUID,
        payload: QARequest,
        hits,
        citations,
        answer_source: str,
        route: QueryRoute,
        related_memories=None,
        citation_score_breakdown: list[dict] | None = None,
        effective_question: str | None = None,
        workflow_steps: list[dict] | None = None,
        agent_error_message: str | None = None,
        execution_plan: dict | None = None,
        extra_metadata: dict | None = None,
    ):
        direct_hit_by_memory = {
            str(hit.memory.id): {
                "rank": rank,
                "score": round(float(hit.score), 6),
                "title": hit.memory.title or "Untitled Memory",
            }
            for rank, hit in enumerate(hits, start=1)
        }
        related_trace = [
            {
                "memory_id": str(item["memory"].id),
                "source_memory_id": item["source_memory_id"],
                "source_memory_title": item.get("source_memory_title") or "Untitled Memory",
                "title": item["memory"].title or "Untitled Memory",
                "relation_type": item["relation_type"],
                "relation_reason": item["relation_reason"],
                "score": round(float(item["relation_score"]), 6),
                "direct_hit_rank": direct_hit_by_memory.get(str(item["memory"].id), {}).get("rank"),
                "direct_hit_score": direct_hit_by_memory.get(str(item["memory"].id), {}).get("score"),
                "ranking_reason": self._relation_ranking_reason(item, direct_hit_by_memory.get(str(item["memory"].id))),
            }
            for item in (related_memories or [])
        ]
        citation_breakdown = citation_score_breakdown or []
        candidate_annotations = self._build_candidate_annotations(
            hits=hits,
            citation_breakdown=citation_breakdown,
        )
        metadata = {
            "retrieval_strategy": "chunk_v1+relation_expand_v1" if related_trace else "chunk_v1",
            "citation_rerank_strategy": "citation_rerank_v1",
            "hit_count": len(hits),
            "citation_count": len(citations),
            "related_memory_count": len(related_trace),
            "related_memory_expansions": related_trace,
            "citation_score_breakdown": citation_breakdown,
            "query_route": route.route,
            "query_intent": route.intent,
            "query_route_reason": route.reason,
            "retrieval_scope": route.retrieval_scope,
            "answer_mode": route.answer_mode,
        }
        if execution_plan:
            metadata["execution_plan"] = execution_plan
        if extra_metadata:
            metadata.update(extra_metadata)
        metadata["workflow_steps"] = workflow_steps or self._build_workflow_steps(
            payload=payload,
            route=route,
            hits=hits,
            citations=citations,
            answer_source=answer_source,
            related_trace=related_trace,
            citation_breakdown=citation_breakdown,
            effective_question=effective_question,
        )
        if effective_question and effective_question != payload.question:
            metadata["effective_question"] = effective_question
            metadata["conversation_context_used"] = True
        else:
            metadata["conversation_context_used"] = False
        if agent_error_message:
            metadata["agent_error_message"] = agent_error_message

        try:
            return retrieval_trace_service.record_qa_trace(
                db,
                user_id=user_id,
                question=payload.question,
                mode=payload.mode,
                hits=hits,
                citations=citations,
                answer_source=answer_source,
                candidate_annotations=candidate_annotations,
                metadata=metadata,
            )
        except Exception:  # noqa: BLE001
            db.rollback()
            return None

    def _build_candidate_annotations(self, *, hits, citation_breakdown: list[dict]) -> dict[str, dict]:
        breakdown_by_memory = {
            str(item.get("memory_id")): item
            for item in citation_breakdown
            if item.get("memory_id")
        }
        annotated: dict[str, dict] = {}
        seen_memory_ids: set[str] = set()
        for rank, hit in enumerate(hits, start=1):
            memory_id = str(hit.memory.id)
            if memory_id in seen_memory_ids:
                continue
            seen_memory_ids.add(memory_id)
            breakdown = breakdown_by_memory.get(memory_id, {})
            exclusion_reason = breakdown.get("exclusion_reason")
            entered_direct_window = rank <= DIRECT_CITATION_WINDOW
            entered_rerank = bool(breakdown) and exclusion_reason not in {"outside_direct_window", "below_direct_score_floor"}
            annotated[memory_id] = {
                "entered_direct_window": entered_direct_window,
                "entered_rerank": entered_rerank,
                "final_selected": bool(breakdown.get("selected")) if breakdown else False,
                "exclusion_reason": exclusion_reason,
                "exclusion_reason_detail": breakdown.get("exclusion_reason_detail"),
                "citation_source": breakdown.get("source"),
                "final_score": breakdown.get("final_score"),
            }
        return annotated

    def _finalize_breakdowns(
        self,
        *,
        direct_hit_meta_by_memory: dict[str, dict],
        candidate_memory_ids: set[str],
        selected_memory_ids: set[str],
        selected_breakdowns: list[dict],
        rejected_breakdowns: list[dict],
    ) -> list[dict]:
        breakdowns = [*selected_breakdowns, *rejected_breakdowns]
        recorded_memory_ids = {str(item.get("memory_id")) for item in breakdowns}
        for memory_id, meta in direct_hit_meta_by_memory.items():
            if memory_id in candidate_memory_ids or memory_id in recorded_memory_ids:
                continue
            breakdowns.append(
                {
                    "memory_id": memory_id,
                    "title": meta["title"],
                    "source": "direct",
                    "direct_score": meta["normalized_score"],
                    "raw_hit_score": meta["raw_score"],
                    "direct_hit_rank": meta["rank"],
                    "relation_score": 0.0,
                    "recency_score": 0.0,
                    "fact_score": 0.0,
                    "source_bonus": 0.0,
                    "final_score": 0.0,
                    "relation_reason": "",
                    "selected": False,
                    "snippet": meta["snippet"],
                    "category": meta["category"],
                }
            )
            if int(meta["rank"]) <= DIRECT_CITATION_WINDOW:
                breakdowns[-1]["score_formula"] = "filtered_before_rerank_score_floor"
                breakdowns[-1]["exclusion_reason"] = "below_direct_score_floor"
                breakdowns[-1]["exclusion_reason_detail"] = (
                    f"直接命中已进入前 {DIRECT_CITATION_WINDOW} 条窗口，但归一化 direct score "
                    f"{float(meta['normalized_score']):.2f} 低于最小阈值 {MIN_DIRECT_SCORE:.2f}，未进入 rerank。"
                )
            else:
                breakdowns[-1]["score_formula"] = "not_entered_rerank_window"
                breakdowns[-1]["exclusion_reason"] = "outside_direct_window"
                breakdowns[-1]["exclusion_reason_detail"] = (
                    f"直接命中排在第 {meta['rank']} 名，初始重排窗口只纳入前 {DIRECT_CITATION_WINDOW} 条 direct hit。"
                )

        breakdowns.sort(
            key=lambda item: (
                0 if item.get("selected") else 1,
                -float(item.get("final_score") or 0.0),
                int(item.get("direct_hit_rank") or 999),
            )
        )
        return breakdowns

    def _relation_ranking_reason(self, item: dict, direct_hit: dict | None = None) -> str:
        relation_type = str(item.get("relation_type") or "")
        relation_score = round(float(item.get("relation_score") or 0.0), 4)
        reason = str(item.get("relation_reason") or "")
        direct_hint = ""
        if direct_hit is not None:
            direct_hint = f" It was also a direct retrieval hit at rank {direct_hit['rank']}."
        if relation_type == "shared_fact":
            return f"Structured fact overlap pushed this memory in with relation score {relation_score}.{direct_hint} {reason}".strip()
        if relation_type == "shared_entity":
            return f"Shared entity/topic overlap pushed this memory in with relation score {relation_score}.{direct_hint} {reason}".strip()
        return f"Semantic overlap pushed this memory in with relation score {relation_score}.{direct_hint} {reason}".strip()

    def _build_execution_plan(
        self,
        *,
        original_question: str,
        effective_question: str,
        mode: str,
        route: QueryRoute,
    ) -> dict:
        normalized_question = " ".join((effective_question or original_question).split())
        split_subquestions = self._split_question_into_subquestions(normalized_question)
        time_window = self._plan_time_window(normalized_question)
        context_packing = self._plan_context_packing(route=route, mode=mode)
        if route.route == "weather":
            subquestions = [
                self._planned_subquestion(
                    question=f"Extract the target location from: {normalized_question}",
                    tool="weather_service",
                    reason="Need a concrete location before calling the weather tool.",
                ),
                self._planned_subquestion(
                    question="Fetch the latest weather conditions for that location.",
                    tool="weather_service",
                    reason="Weather questions should resolve through the weather tool.",
                ),
            ]
            tools = ["weather_service"]
            summary = "Use the weather tool after extracting the location from the question."
        elif route.route == "web":
            subquestions = [
                self._planned_subquestion(
                    question=f"Clarify the external information need in: {normalized_question}",
                    tool="web_search_service",
                    reason="The question asks for external or recent information.",
                ),
                self._planned_subquestion(
                    question="Search the web for recent and relevant sources.",
                    tool="web_search_service",
                    reason="Recent external knowledge should come from the web tool.",
                ),
                self._planned_subquestion(
                    question="Answer concisely with citations from those sources.",
                    tool="web_search_service",
                    reason="Ground the final answer in retrieved web citations.",
                ),
            ]
            tools = ["web_search_service"]
            summary = "Use the web search tool and answer from external sources with citations."
        elif route.route == "fact":
            subquestions = [
                self._planned_subquestion(
                    question=f"Find structured personal facts relevant to: {normalized_question}",
                    tool="fact_insight_service",
                    reason="The route points to structured personal facts.",
                ),
                self._planned_subquestion(
                    question=f"Summarize the strongest {route.intent or 'personal_fact'} signals into a direct answer.",
                    tool="fact_insight_service",
                    reason="The fact insight layer can answer directly from extracted facts.",
                ),
            ]
            tools = ["fact_insight_service"]
            summary = "Answer from structured personal facts before falling back to broader retrieval."
        elif route.route == "insight":
            subquestions = [
                self._planned_subquestion(
                    question=f"Select the most relevant personal insight cards for: {normalized_question}",
                    tool="dashboard_service",
                    reason="Personal insight questions should aggregate over existing insight cards first.",
                ),
                self._planned_subquestion(
                    question="Summarize the strongest patterns into a concise personal insight answer.",
                    tool="dashboard_service",
                    reason="Insight cards already encode summarized personal trends and signals.",
                ),
            ]
            tools = ["dashboard_service"]
            summary = "Answer from personal insight cards and summarized trends."
        elif route.route == "direct":
            subquestions = [
                self._planned_subquestion(
                    question=f"Answer the user directly: {normalized_question}",
                    tool="direct_response",
                    reason="The question is a general chat/capability query and should not be forced into memory retrieval.",
                )
            ]
            tools = ["direct_response"]
            summary = "Answer directly without retrieval or active-document grounding."
        elif route.route == "clarify":
            subquestions = [
                self._planned_subquestion(
                    question=f"Ask the user to clarify the scope of: {normalized_question}",
                    tool="clarification_prompt",
                    reason="The query is ambiguous and should not trigger retrieval until scope is clear.",
                )
            ]
            tools = ["clarification_prompt"]
            summary = "Ask one short clarification question before retrieval."
        else:
            memory_subquestions = split_subquestions or [normalized_question]
            subquestions = [
                *[
                    self._planned_subquestion(
                        question=f"Retrieve personal memories relevant to: {item}",
                        tool="chunk_service",
                        reason="Memory questions should start from direct chunk retrieval.",
                    )
                    for item in memory_subquestions
                ],
                self._planned_subquestion(
                    question="Expand related memories when relation edges can improve grounding.",
                    tool="memory_relation_service",
                    reason="Relation edges can recover supporting memories outside the direct window.",
                ),
                self._planned_subquestion(
                    question="Rerank citations before final answer generation.",
                    tool="llm_answer_service",
                    reason="The final answer should be grounded in reranked citations.",
                ),
            ]
            tools = ["chunk_service", "memory_relation_service", "llm_answer_service"]
            summary = "Answer from personal memory retrieval, relation expansion, and citation reranking."

        if mode == "hybrid_web" and route.route == "memory":
            tools.append("web_search_service_fallback")
            summary = f"{summary} Keep a web-search fallback available because hybrid mode is enabled."

        return {
            "planner_version": "rule_based_v2",
            "summary": summary,
            "route": route.route,
            "intent": route.intent,
            "mode": mode,
            "subquestions": subquestions,
            "tools": tools,
            "time_window": time_window,
            "context_packing": context_packing,
        }

    def _plan_time_window(self, question: str) -> dict:
        window = fact_insight_service._resolve_time_window(question)
        return self._serialize_time_window(window)

    def _serialize_time_window(self, window: TimeWindow) -> dict:
        return {
            "label": window.label,
            "start": window.start.isoformat() if window.start else None,
            "end": window.end.isoformat() if window.end else None,
        }

    def _plan_context_packing(self, *, route: QueryRoute, mode: str) -> dict:
        if route.route == "fact":
            return {
                "strategy": "structured_fact_first",
                "max_direct_hits": 0,
                "max_related_memories": 0,
                "prefer": ["facts", "citations"],
            }
        if route.route == "web":
            return {
                "strategy": "web_first_with_memory_context",
                "max_direct_hits": 2,
                "max_related_memories": 0,
                "prefer": ["web_results", "memory_context"],
            }
        if route.route == "weather":
            return {
                "strategy": "tool_only",
                "max_direct_hits": 0,
                "max_related_memories": 0,
                "prefer": ["tool_result"],
            }
        if route.route in {"direct", "clarify"}:
            return {
                "strategy": "no_retrieval",
                "max_direct_hits": 0,
                "max_related_memories": 0,
                "prefer": ["direct_answer" if route.route == "direct" else "clarification"],
            }
        return {
            "strategy": "memory_rag",
            "max_direct_hits": 5,
            "max_related_memories": 4,
            "prefer": ["direct_hits", "related_memories", "reranked_citations"],
            "web_fallback": mode == "hybrid_web",
        }

    def _split_question_into_subquestions(self, question: str) -> list[str]:
        normalized = " ".join(question.replace("？", "?").replace("，", ",").split())
        if not normalized:
            return []
        separators = [" and ", "然后", "并且", "同时", "以及", ",", "?", "；", ";"]
        segments = [normalized]
        for separator in separators:
            next_segments: list[str] = []
            for segment in segments:
                if separator in segment:
                    next_segments.extend(part.strip() for part in segment.split(separator))
                else:
                    next_segments.append(segment)
            segments = next_segments
        cleaned = [segment.strip(" ,?;") for segment in segments if len(segment.strip(" ,?;")) >= 4]
        deduped: list[str] = []
        seen: set[str] = set()
        for segment in cleaned:
            key = segment.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(segment)
        return deduped[:4]

    def _planned_subquestion(self, *, question: str, tool: str, reason: str) -> dict:
        return {
            "question": question,
            "tool": tool,
            "reason": reason,
        }

    def _make_workflow_step(
        self,
        *,
        key: str,
        label: str,
        status: str,
        detail: str,
        metric: str | None = None,
        duration_ms: float | None = None,
        error_message: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        started_at = datetime.now(timezone.utc)
        completed_at = started_at if status not in {"running", "pending"} else None
        return {
            "key": key,
            "label": label,
            "status": status,
            "detail": detail,
            "metric": metric,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat() if completed_at is not None else None,
            "duration_ms": duration_ms,
            "error_message": error_message,
            "metadata": dict(metadata or {}),
        }

    def _timed_call(self, func):
        started = perf_counter()
        result = func()
        duration_ms = round((perf_counter() - started) * 1000.0, 3)
        return result, duration_ms

    def _build_workflow_steps(
        self,
        *,
        payload: QARequest,
        route: QueryRoute,
        hits,
        citations,
        answer_source: str,
        related_trace: list[dict],
        citation_breakdown: list[dict],
        effective_question: str | None,
    ) -> list[dict]:
        steps = [
            {
                "key": "query_route",
                "label": "判断问题意图",
                "status": "done",
                "detail": route.reason,
                "metric": route.intent,
            }
        ]
        if effective_question and effective_question != payload.question:
            steps.append(
                {
                    "key": "followup_rewrite",
                    "label": "补全追问上下文",
                    "status": "done",
                    "detail": "短追问已结合最近对话改写为可检索问题。",
                    "metric": "context_used",
                }
            )
        steps.append(
            {
                "key": "chunk_retrieval",
                "label": "检索候选片段",
                "status": "done",
                "detail": f"从记忆 chunk 中召回 {len(hits)} 条候选。",
                "metric": str(len(hits)),
            }
        )
        if related_trace:
            steps.append(
                {
                    "key": "relation_expand",
                    "label": "扩展相关记忆",
                    "status": "done",
                    "detail": f"通过关系边补入 {len(related_trace)} 条相关记忆。",
                    "metric": str(len(related_trace)),
                }
            )
        if citation_breakdown:
            selected_count = sum(1 for item in citation_breakdown if item.get("selected") is True)
            steps.append(
                {
                    "key": "citation_rerank",
                    "label": "重排引用来源",
                    "status": "done",
                    "detail": f"按直接命中、关系补强、时间新近和事实置信重排，保留 {selected_count} 条引用。",
                    "metric": str(selected_count),
                }
            )
        steps.append(
            {
                "key": "answer_generation",
                "label": "生成可追溯回答",
                "status": "done",
                "detail": self._workflow_answer_detail(answer_source, len(citations)),
                "metric": answer_source,
            }
        )
        return steps

    def _workflow_answer_detail(self, answer_source: str, citation_count: int) -> str:
        if answer_source == "fact_insight":
            return f"Used structured facts to answer and kept {citation_count} supporting citations."
        if answer_source == "insight_agent":
            return f"Used personal insight cards to answer and kept {citation_count} supporting citations."
        if answer_source == "weather_tool":
            return "Used the weather tool to answer the question."
        if answer_source == "web_tool":
            return f"Used the web tool to answer and kept {citation_count} supporting citations."
        if answer_source == "direct_answer":
            return "Answered directly without retrieval or active-document grounding."
        if answer_source == "clarify":
            return "Asked a short clarification question before any retrieval."
        if answer_source == "weather_tool_unavailable":
            return "Detected a weather question but the weather tool was unavailable, so the answer stayed out of memory retrieval."
        if answer_source == "web_tool_unavailable":
            return "Detected an external-information question but the web tool was unavailable, so the answer stayed out of memory retrieval."
        return f"Used retrieved memory context to answer and kept {citation_count} supporting citations."


qa_service = QAService()
