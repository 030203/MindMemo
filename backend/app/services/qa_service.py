from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.schemas.qa import QARouteInfo, QASlowRouteInfo, QASourceInfo, SimpleQARequest, SimpleQAResponse
from app.orchestration.qa_workflow import qa_workflow


class QAService:
    async def answer_question(self, db: Session, user_id: uuid.UUID, payload: SimpleQARequest) -> SimpleQAResponse:
        out = await qa_workflow.run(
            question=payload.question,
            user_id=user_id,
            db=db,
        )
        route = out.get("route") or {}
        slow_route = out.get("slow_route")
        sources_raw = out.get("sources") or []

        return SimpleQAResponse(
            answer=out.get("answer") or "抱歉，AI 服务当前不可用。请检查 API Key 配置。",
            route=QARouteInfo(
                complexity=route.get("complexity", "fast"),
                reason=route.get("reason", ""),
                decided_by=route.get("decided_by", "rule"),
            ),
            slow_route=QASlowRouteInfo(
                path=(slow_route or {}).get("path", "react"),
                reason=(slow_route or {}).get("reason", ""),
                decided_by=(slow_route or {}).get("decided_by", "llm"),
            ) if slow_route else None,
            sources=[
                QASourceInfo(memory_id=s.get("memory_id", ""), title=s.get("title", ""))
                for s in sources_raw
            ],
            tool_calls_made=out.get("tool_calls_made", 0),
        )


qa_service = QAService()
