import asyncio
import json
import logging
import threading
import uuid
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user_id
from app.orchestration.qa_workflow import qa_workflow
from app.orchestration.router import Router
from app.repos.chat_repo import chat_repository
from app.schemas.chat import (
    ChatMessageResponse,
    ChatSessionCreateRequest,
    ChatSessionResponse,
    SessionQARequest,
    SessionQAResponse,
    SessionUpdateRequest,
)
from app.schemas.common import ApiResponse
from app.services.chat_service import chat_service
from app.services.llm_answer_service import llm_answer_service

router = APIRouter()
_global_router = Router()


@router.get("/sessions")
def list_sessions(
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[list[ChatSessionResponse]]:
    sessions = chat_service.list_sessions(db, user_id)
    return ApiResponse(data=[
        ChatSessionResponse(
            session_id=s.id,
            context_type=s.context_type,
            context_id=s.context_id,
            title=s.title,
            created_at=s.created_at,
            pinned=getattr(s, "pinned", False),
        )
        for s in sessions
    ])


@router.post("/sessions")
def create_or_get_session(
    payload: ChatSessionCreateRequest,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[ChatSessionResponse]:
    session = chat_service.get_or_create_session(
        db, user_id,
        context_type=payload.context_type,
        context_id=payload.context_id,
        title=payload.title,
    )
    db.commit()
    return ApiResponse(data=ChatSessionResponse(
        session_id=session.id,
        context_type=session.context_type,
        context_id=session.context_id,
        title=session.title,
        created_at=session.created_at,
        pinned=getattr(session, "pinned", False),
    ))


@router.get("/sessions/{session_id}/messages")
def get_session_messages(
    session_id: str,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[list[ChatMessageResponse]]:
    session = chat_service.get_session_for_user(db, user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = chat_repository.list_messages(db, session_id, limit=50)
    return ApiResponse(data=[
        ChatMessageResponse(
            id=m.id,
            role=m.role,
            content=m.content,
            created_at=m.created_at,
        )
        for m in messages
    ])


@router.post("/sessions/{session_id}/ask")
async def ask_in_session(
    session_id: str,
    payload: SessionQARequest,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[SessionQAResponse]:
    session = chat_service.get_session_for_user(db, user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    history = chat_service.get_history_window(db, session_id)

    # 走 Router + QAWorkflow 编排层（支持工具调用）
    result = await qa_workflow.run(
        question=payload.question,
        history=history,
        user_id=user_id,
        db=db,
    )
    full_answer = (result.get("answer") or "").strip()

    if not full_answer:
        return ApiResponse(data=SessionQAResponse(
            answer="抱歉，AI 服务暂时不可用。",
            session_id=session_id,
            message_id="",
        ))

    msg = chat_service.append_exchange(db, session_id, payload.question, full_answer)
    db.commit()
    chat_service.auto_title_if_needed(db, session_id, payload.question)
    return ApiResponse(data=SessionQAResponse(
        answer=full_answer,
        session_id=session_id,
        message_id=msg.id,
    ))


@router.post("/sessions/{session_id}/ask-stream")
async def ask_in_session_stream(
    session_id: str,
    payload: SessionQARequest,
    request: Request,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
):
    """SSE 流式问答端点 — 先路由分类，再决定走纯流式还是编排层。"""
    session = chat_service.get_session_for_user(db, user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    history = chat_service.get_history_window(db, session_id)
    context_doc = chat_service.build_context_doc(
        db, user_id, session.context_type, session.context_id,
    )

    # 全局会话无 context_doc 时，做轻量记忆检索补充上下文
    if not context_doc and session.context_type == "global":
        context_doc = chat_service.build_global_context(
            db, user_id, payload.question,
        )

    # [Phase 1] 路由分类
    route = _global_router.route(payload.question)

    async def event_stream() -> AsyncGenerator[str, None]:
        # ── Fast + 无工具：纯流式聊天 ──────────────────────────
        if route.is_fast and not route.suggested_tools:
            queue: asyncio.Queue = asyncio.Queue(maxsize=64)
            full_answer_chunks: list[str] = []
            stream_error: list[str] = []

            def run_sync():
                try:
                    for chunk in llm_answer_service.chat_stream(
                        question=payload.question,
                        history=history,
                        context_doc=context_doc,
                    ):
                        asyncio.run_coroutine_threadsafe(queue.put(("chunk", chunk)), loop)
                    asyncio.run_coroutine_threadsafe(queue.put(("done", None)), loop)
                except Exception as exc:
                    stream_error.append(str(exc))
                    asyncio.run_coroutine_threadsafe(queue.put(("error", str(exc))), loop)

            loop = asyncio.get_running_loop()
            thread = threading.Thread(target=run_sync, daemon=True)
            thread.start()

            while True:
                kind, data = await queue.get()
                if kind == "chunk":
                    full_answer_chunks.append(data)
                    yield f"data: {json.dumps({'type': 'chunk', 'content': data}, ensure_ascii=False)}\n\n"
                elif kind == "done":
                    break
                elif kind == "error":
                    yield f"data: {json.dumps({'type': 'error', 'content': 'AI 服务暂时不可用'})}\n\n"
                    return

            thread.join(timeout=5)
            full_answer = "".join(full_answer_chunks)

            if stream_error:
                yield f"data: {json.dumps({'type': 'error', 'content': 'AI 服务异常'})}\n\n"
                return

            if not full_answer:
                yield f"data: {json.dumps({'type': 'error', 'content': 'AI 返回为空'})}\n\n"
                return

            msg = chat_service.append_exchange(db, session_id, payload.question, full_answer)
            db.commit()
            chat_service.auto_title_if_needed(db, session_id, payload.question)
            yield f"data: {json.dumps({'type': 'done', 'message_id': msg.id}, ensure_ascii=False)}\n\n"
            return

        # ── Fast + 工具 / Slow：统一走真流式 ─────────────────────
        # 对有 context_doc（memory 上下文）的请求，直接用 chat_stream 实现真正流式；
        # 对外部工具类请求，仍走编排层但保持流式推送。
        if context_doc and not route.suggested_tools:
            # 有记录上下文 → 直接流式 LLM，带 context_doc
            queue2: asyncio.Queue = asyncio.Queue(maxsize=64)
            full_chunks: list[str] = []
            stream_err: list[str] = []

            loop2 = asyncio.get_running_loop()

            def run_sync2():
                try:
                    for chunk in llm_answer_service.chat_stream(
                        question=payload.question,
                        history=history,
                        context_doc=context_doc,
                    ):
                        asyncio.run_coroutine_threadsafe(queue2.put(("chunk", chunk)), loop2)
                    asyncio.run_coroutine_threadsafe(queue2.put(("done", None)), loop2)
                except Exception as exc:
                    stream_err.append(str(exc))
                    asyncio.run_coroutine_threadsafe(queue2.put(("error", str(exc))), loop2)

            thread2 = threading.Thread(target=run_sync2, daemon=True)
            thread2.start()

            while True:
                kind, data = await queue2.get()
                if kind == "chunk":
                    full_chunks.append(data)
                    yield f"data: {json.dumps({'type': 'chunk', 'content': data}, ensure_ascii=False)}\n\n"
                elif kind == "done":
                    break
                elif kind == "error":
                    yield f"data: {json.dumps({'type': 'error', 'content': 'AI 服务暂时不可用'})}\n\n"
                    return

            thread2.join(timeout=5)
            full_answer2 = "".join(full_chunks)

            if stream_err or not full_answer2:
                yield f"data: {json.dumps({'type': 'error', 'content': 'AI 返回为空'})}\n\n"
                return

            msg = chat_service.append_exchange(db, session_id, payload.question, full_answer2)
            db.commit()
            chat_service.auto_title_if_needed(db, session_id, payload.question)
            yield f"data: {json.dumps({'type': 'done', 'message_id': msg.id}, ensure_ascii=False)}\n\n"
            return

        # 无 context_doc 但有工具（天气/搜索等）→ 走编排层
        try:
            result = await qa_workflow.run(
                question=payload.question,
                history=history,
                user_id=user_id,
                db=db,
            )
            answer = (result.get("answer") or "").strip()
        except Exception as exc:
            logger.exception("qa_workflow.run 异常: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'content': 'AI 服务暂时不可用'})}\n\n"
            return

        if not answer:
            yield f"data: {json.dumps({'type': 'error', 'content': 'AI 服务暂时不可用'})}\n\n"
            return

        msg = chat_service.append_exchange(db, session_id, payload.question, answer)
        try:
            db.commit()
        except Exception as exc:
            logger.warning("保存对话记录失败: %s", exc)
        chat_service.auto_title_if_needed(db, session_id, payload.question)

        # 编排层结果是完整回答，一次性推送整段；
        # 逐字打字机效果由前端节流渲染，后端无需再切块。
        yield f"data: {json.dumps({'type': 'chunk', 'content': answer}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'message_id': msg.id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.patch("/sessions/{session_id}")
def update_session(
    session_id: str,
    payload: SessionUpdateRequest,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[ChatSessionResponse]:
    session = chat_service.get_session_for_user(db, user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if payload.title is not None:
        session.title = payload.title[:255]
    if payload.pinned is not None:
        session.pinned = payload.pinned
    db.commit()
    db.refresh(session)
    return ApiResponse(data=ChatSessionResponse(
        session_id=session.id,
        context_type=session.context_type,
        context_id=session.context_id,
        title=session.title,
        created_at=session.created_at,
        pinned=getattr(session, "pinned", False),
    ))


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
    user_id=Depends(get_current_user_id),
) -> ApiResponse[dict]:
    session = chat_service.get_session_for_user(db, user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    from app.repos.chat_repo import chat_repository
    chat_repository.soft_delete(db, session)
    db.commit()
    return ApiResponse(data={"deleted": True})
