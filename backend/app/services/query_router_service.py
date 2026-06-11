from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QueryRoute:
    route: str
    intent: str
    reason: str
    scope: str = "global"
    task_type: str = "detail_qa"
    context_mode: str = "local_qa"
    needs_full_coverage: bool = False
    needs_exact_evidence: bool = True
    should_retrieve: bool = True
    should_use_active_context: bool = False
    should_ask_clarification: bool = False
    retrieval_scope: str = "global_kb"
    answer_mode: str = "grounded_qa"

    def as_dict(self) -> dict:
        return {
            "route": self.route,
            "intent": self.intent,
            "reason": self.reason,
            "scope": self.scope,
            "task_type": self.task_type,
            "context_mode": self.context_mode,
            "needs_full_coverage": self.needs_full_coverage,
            "needs_exact_evidence": self.needs_exact_evidence,
            "should_retrieve": self.should_retrieve,
            "should_use_active_context": self.should_use_active_context,
            "should_ask_clarification": self.should_ask_clarification,
            "retrieval_scope": self.retrieval_scope,
            "answer_mode": self.answer_mode,
        }


class QueryRouterService:
    def route(self, question: str, mode: str, active_context: dict[str, Any] | None = None) -> QueryRoute:
        text = question.strip()
        lowered = text.lower()
        if not text:
            return QueryRoute(
                route="memory",
                intent="empty",
                reason="empty_query",
                should_retrieve=False,
                retrieval_scope="none",
                answer_mode="direct_answer",
            )

        context_route = self._route_active_context(text, lowered, mode, active_context)
        if context_route is not None:
            return context_route

        if self._looks_like_timeline(text, lowered):
            return QueryRoute(
                route="memory",
                intent="timeline",
                reason="timeline_marker",
                task_type="mixed",
                context_mode="global_then_local",
                should_use_active_context=False,
                retrieval_scope="global_kb",
                answer_mode="grounded_timeline",
            )

        if self._looks_like_aggregation(text, lowered):
            return QueryRoute(
                route="fact",
                intent="aggregation",
                reason="aggregation_marker",
                task_type="summary",
                context_mode="full_summary",
                needs_full_coverage=True,
                needs_exact_evidence=False,
                should_retrieve=False,
                retrieval_scope="none",
                answer_mode="fact_summary",
            )

        if self._looks_like_insight(text, lowered):
            return QueryRoute(
                route="insight",
                intent="personal_insight",
                reason="insight_marker",
                task_type="summary",
                context_mode="full_summary",
                needs_full_coverage=True,
                needs_exact_evidence=False,
                should_retrieve=False,
                retrieval_scope="none",
                answer_mode="insight_summary",
            )

        direct_route = self._route_direct_or_tool(text, lowered, mode)
        if direct_route is not None:
            return direct_route

        if self._looks_like_weather(text, lowered):
            return QueryRoute(
                route="weather",
                intent="weather",
                reason="weather_marker",
                context_mode="global_then_local",
                should_retrieve=False,
                retrieval_scope="none",
                answer_mode="tool_answer",
            )

        fact_intent = self._fact_intent(text, lowered)
        if fact_intent:
            return QueryRoute(
                route="fact",
                intent=fact_intent,
                reason="structured_personal_fact",
                should_retrieve=False,
                retrieval_scope="none",
                answer_mode="fact_answer",
            )

        if mode == "hybrid_web" and self._looks_like_web(text, lowered):
            return QueryRoute(
                route="web",
                intent="web_search",
                reason="explicit_web_marker",
                context_mode="global_then_local",
                should_retrieve=False,
                retrieval_scope="none",
                answer_mode="tool_answer",
            )

        if mode == "hybrid_web":
            return QueryRoute(
                route="web",
                intent="web_search",
                reason="hybrid_web_default",
                context_mode="global_then_local",
                should_retrieve=False,
                retrieval_scope="none",
                answer_mode="tool_answer",
            )

        return QueryRoute(
            route="memory",
            intent="memory_recall",
            reason="memory_mode_default",
            retrieval_scope="global_kb",
            answer_mode="grounded_qa",
        )

    def _route_active_context(self, text: str, lowered: str, mode: str, active_context: dict[str, Any] | None) -> QueryRoute | None:
        context = active_context or {}
        if not self._has_active_context(context):
            return None

        direct_route = self._route_direct_or_tool(text, lowered, mode=mode, include_open_chat=False)
        if direct_route is not None:
            return direct_route

        if self._looks_like_ambiguous_context_query(text, lowered):
            return QueryRoute(
                route="clarify",
                intent="clarify_scope",
                reason="active_context_ambiguous_scope_rule",
                scope="global",
                task_type="clarify",
                context_mode="clarify",
                needs_full_coverage=False,
                needs_exact_evidence=False,
                should_retrieve=False,
                should_use_active_context=False,
                should_ask_clarification=True,
                retrieval_scope="none",
                answer_mode="clarify",
            )

        scope = self._context_scope(text, lowered, context)
        if scope == "global":
            return None

        selected_text = str(context.get("selected_text") or "").strip()
        if selected_text and self._has_any(text, lowered, self._selected_text_markers()):
            return QueryRoute(
                route="memory",
                intent="selected_text_qa",
                reason="active_context_selected_text_rule",
                scope=scope,
                task_type="selected_text_qa",
                context_mode="direct_selected_text",
                needs_full_coverage=False,
                needs_exact_evidence=True,
                should_use_active_context=True,
            )

        if self._looks_like_global_then_local(text, lowered):
            return QueryRoute(
                route="memory",
                intent="context_global_then_local",
                reason="active_context_mixed_rule",
                scope=scope,
                task_type="mixed",
                context_mode="global_then_local",
                needs_full_coverage=True,
                needs_exact_evidence=True,
                should_use_active_context=True,
                retrieval_scope=self._context_retrieval_scope(scope),
                answer_mode="grounded_review",
            )

        transform_intent = self._detect_transform_intent(text, lowered)
        if transform_intent is not None:
            return QueryRoute(
                route="document_op",
                intent=transform_intent,
                reason="active_context_transform_rule",
                scope=scope,
                task_type="doc_op",
                context_mode="transform_full_context",
                needs_full_coverage=True,
                needs_exact_evidence=False,
                should_retrieve=False,
                should_use_active_context=True,
                retrieval_scope=self._context_retrieval_scope(scope),
                answer_mode="transform",
            )

        if self._has_any(text, lowered, self._summary_markers()):
            return QueryRoute(
                route="document_op",
                intent="doc_summary",
                reason="active_context_summary_rule",
                scope=scope,
                task_type="doc_op",
                context_mode="full_summary",
                needs_full_coverage=True,
                needs_exact_evidence=False,
                should_use_active_context=True,
                should_retrieve=False,
                retrieval_scope=self._context_retrieval_scope(scope),
                answer_mode="summarize",
            )

        if self._has_any(text, lowered, self._extraction_markers()):
            return QueryRoute(
                route="document_op",
                intent="doc_extract",
                reason="active_context_extraction_rule",
                scope=scope,
                task_type="doc_op",
                context_mode="exhaustive_extract",
                needs_full_coverage=True,
                needs_exact_evidence=True,
                should_use_active_context=True,
                should_retrieve=False,
                retrieval_scope=self._context_retrieval_scope(scope),
                answer_mode="extract",
            )

        if self._looks_like_context_review(text, lowered, scope=scope):
            return QueryRoute(
                route="memory",
                intent="context_review",
                reason="active_context_review_rule",
                scope=scope,
                task_type="mixed",
                context_mode="global_then_local",
                needs_full_coverage=True,
                needs_exact_evidence=True,
                should_use_active_context=True,
                retrieval_scope=self._context_retrieval_scope(scope),
                answer_mode="grounded_review",
            )

        if self._has_any(text, lowered, self._detail_markers()):
            return QueryRoute(
                route="memory",
                intent="context_detail_qa",
                reason="active_context_detail_rule",
                scope=scope,
                task_type="detail_qa",
                context_mode="local_qa",
                needs_full_coverage=False,
                needs_exact_evidence=True,
                should_use_active_context=True,
                retrieval_scope=self._context_retrieval_scope(scope),
                answer_mode="grounded_qa",
            )

        if scope == "current_document":
            return QueryRoute(
                route="memory",
                intent="context_document_understanding",
                reason="active_context_document_default_mixed_rule",
                scope=scope,
                task_type="mixed",
                context_mode="global_then_local",
                needs_full_coverage=True,
                needs_exact_evidence=True,
                should_use_active_context=True,
                retrieval_scope=self._context_retrieval_scope(scope),
                answer_mode="grounded_review",
            )

        return QueryRoute(
            route="memory",
            intent="context_detail_qa",
            reason="active_context_default_local_rule",
            scope=scope,
            task_type="detail_qa",
            context_mode="local_qa",
            needs_full_coverage=False,
            needs_exact_evidence=True,
            should_use_active_context=True,
            retrieval_scope=self._context_retrieval_scope(scope),
            answer_mode="grounded_qa",
        )

    def _route_direct_or_tool(self, text: str, lowered: str, mode: str, *, include_open_chat: bool = True) -> QueryRoute | None:
        if self._looks_like_identity_or_capability_chat(text, lowered):
            return QueryRoute(
                route="direct",
                intent="general_chat",
                reason="general_chat_marker",
                task_type="direct_answer",
                context_mode="direct_answer",
                needs_full_coverage=False,
                needs_exact_evidence=False,
                should_retrieve=False,
                should_use_active_context=False,
                retrieval_scope="none",
                answer_mode="direct_answer",
            )
        if self._looks_like_weather(text, lowered):
            return QueryRoute(
                route="weather",
                intent="weather",
                reason="weather_marker",
                context_mode="global_then_local",
                needs_full_coverage=False,
                needs_exact_evidence=False,
                should_retrieve=False,
                should_use_active_context=False,
                retrieval_scope="none",
                answer_mode="tool_answer",
            )
        if mode == "hybrid_web" and self._looks_like_web(text, lowered):
            return QueryRoute(
                route="web",
                intent="web_search",
                reason="explicit_web_marker",
                context_mode="global_then_local",
                needs_full_coverage=False,
                needs_exact_evidence=False,
                should_retrieve=False,
                should_use_active_context=False,
                retrieval_scope="none",
                answer_mode="tool_answer",
            )
        if include_open_chat and self._looks_like_open_chat(text, lowered):
            return QueryRoute(
                route="direct",
                intent="open_chat",
                reason="open_chat_marker",
                task_type="direct_answer",
                context_mode="direct_answer",
                needs_full_coverage=False,
                needs_exact_evidence=False,
                should_retrieve=False,
                should_use_active_context=False,
                retrieval_scope="none",
                answer_mode="direct_answer",
            )
        return None

    def _has_active_context(self, context: dict[str, Any]) -> bool:
        active_type = str(context.get("active_context_type") or "none")
        return bool(
            active_type in {"document", "record"}
            or context.get("active_doc_id")
            or context.get("active_record_id")
            or context.get("context_memory_id")
            or str(context.get("selected_text") or "").strip()
        )

    def _context_scope(self, text: str, lowered: str, context: dict[str, Any]) -> str:
        if self._has_any(text, lowered, self._global_markers()):
            return "global"
        active_type = str(context.get("active_context_type") or "none")
        if active_type == "document" or context.get("active_doc_id"):
            return "current_document"
        if active_type == "record" or context.get("active_record_id") or context.get("context_memory_id"):
            return "current_record"
        return "current_record"

    def _context_retrieval_scope(self, scope: str) -> str:
        if scope == "current_document":
            return "active_document"
        if scope == "current_record":
            return "active_record"
        return "global_kb"

    def _looks_like_global_then_local(self, text: str, lowered: str) -> bool:
        has_global = self._has_any(
            text,
            lowered,
            ["整体", "全文", "总体", "整体观点", "总体观点", "overall", "whole document", "whole file"],
        )
        has_local = self._has_any(
            text,
            lowered,
            ["证据", "依据", "哪里", "为什么", "重要", "部分", "这段", "这里", "evidence", "why"],
        )
        return (has_global and has_local) or ("先" in text and ("再" in text or "然后" in text))

    def _looks_like_context_review(self, text: str, lowered: str, *, scope: str) -> bool:
        if self._has_any(
            text,
            lowered,
            ["如何", "怎么样", "怎么看", "评价", "分析", "review", "assess", "evaluate", "thoughts", "opinion"],
        ):
            return True
        return scope == "current_document" and self._looks_like_open_chat(text, lowered)

    def _detect_transform_intent(self, text: str, lowered: str) -> str | None:
        if any(marker in text for marker in ["翻译", "译成"]) or "translate" in lowered:
            return "doc_translate"
        if any(marker in text for marker in ["周报"]) or "weekly report" in lowered:
            return "doc_rewrite_weekly_report"
        if any(marker in text for marker in ["邮件"]) or "email" in lowered:
            return "doc_rewrite_email"
        if any(marker in text for marker in ["改写", "润色", "重写", "整理成", "改成", "转成"]) or any(
            marker in lowered for marker in ["rewrite", "polish", "rephrase"]
        ):
            return "doc_rewrite"
        return None

    def _has_any(self, text: str, lowered: str, markers: list[str]) -> bool:
        return any(marker in text or marker.lower() in lowered for marker in markers)

    def _summary_markers(self) -> list[str]:
        return [
            "总结",
            "概括",
            "主要内容",
            "整体讲了什么",
            "这一天总结",
            "主要讲什么",
            "主要在讲什么",
            "这篇文章主要讲什么",
            "这份文件讲了什么",
            "这条记录讲了什么",
            "帮我看看这条记录",
            "帮我看看这份文件",
            "看看这条记录",
            "看看这份文件",
            "summarize",
            "summary",
            "overview",
        ]

    def _extraction_markers(self) -> list[str]:
        return [
            "所有",
            "全部",
            "哪些",
            "列出",
            "提取",
            "整理出",
            "时间线",
            "待办",
            "风险点",
            "付款节点",
            "all",
            "list",
            "extract",
            "timeline",
            "todos",
            "risks",
        ]

    def _detail_markers(self) -> list[str]:
        return [
            "几点",
            "多少",
            "为什么",
            "在哪里",
            "谁",
            "什么意思",
            "怎么做",
            "哪儿",
            "哪一",
            "how much",
            "when",
            "where",
            "who",
            "why",
            "what does",
        ]

    def _selected_text_markers(self) -> list[str]:
        return [
            "这段",
            "这句话",
            "这里",
            "选中的内容",
            "选中文本",
            "这部分",
            "this passage",
            "selected text",
            "this sentence",
        ]

    def _global_markers(self) -> list[str]:
        return [
            "所有记录",
            "全部记录",
            "所有文件",
            "全部文件",
            "全局",
            "全库",
            "所有记忆",
            "全部记忆",
            "跨记录",
            "跨文件",
            "all records",
            "all files",
            "global",
        ]

    def _looks_like_weather(self, text: str, lowered: str) -> bool:
        return any(marker in text for marker in ["天气", "气温", "下雨"]) or any(
            marker in lowered for marker in ["weather", "temperature", "rain forecast"]
        )

    def _looks_like_web(self, text: str, lowered: str) -> bool:
        return any(
            marker in text
            for marker in ["联网", "搜一下", "查一下", "最新", "新闻", "官网", "网上"]
        ) or any(marker in lowered for marker in ["search web", "latest", "news", "online"])

    def _looks_like_timeline(self, text: str, lowered: str) -> bool:
        return any(marker in text for marker in ["时间线", "按时间", "最近发生", "之前发生", "这周发生", "上周发生"]) or any(
            marker in lowered for marker in ["timeline", "what happened", "recently happened"]
        )

    def _looks_like_aggregation(self, text: str, lowered: str) -> bool:
        return any(marker in text for marker in ["总共", "合计", "统计", "趋势", "概况", "汇总"]) or any(
            marker in lowered for marker in ["summary", "aggregate", "overview", "trend"]
        )

    def _looks_like_open_chat(self, text: str, lowered: str) -> bool:
        return (len(text) <= 18 and any(marker in text for marker in ["聊聊", "说说", "随便聊", "怎么看"])) or any(
            marker in lowered for marker in ["chat", "talk about", "what do you think"]
        )

    def _looks_like_identity_or_capability_chat(self, text: str, lowered: str) -> bool:
        return any(
            marker in text
            for marker in [
                "你是谁",
                "你是干什么的",
                "你能做什么",
                "你会什么",
                "介绍一下你自己",
                "你可以帮我做什么",
            ]
        ) or any(
            marker in lowered
            for marker in [
                "who are you",
                "what can you do",
                "introduce yourself",
                "help me with",
            ]
        )

    def _looks_like_ambiguous_context_query(self, text: str, lowered: str) -> bool:
        compact = text.strip()
        if len(compact) > 12:
            return False
        return any(
            marker in compact
            for marker in [
                "这个怎么样",
                "这个呢",
                "然后呢",
                "继续",
                "展开说说",
                "怎么看",
                "这个",
            ]
        ) or any(marker in lowered for marker in ["what about this", "continue", "and then"])

    def _looks_like_insight(self, text: str, lowered: str) -> bool:
        return any(
            marker in text for marker in ["洞察", "概况", "总结一下", "分析一下", "最近主要", "项目进展", "研究哪些", "消费概况"]
        ) or any(marker in lowered for marker in ["insight", "summarize", "analyze", "overview"])

    def _fact_intent(self, text: str, lowered: str) -> str | None:
        if any(marker in text for marker in ["花了", "消费", "开销", "支出", "花费", "多少钱", "买了", "花钱"]):
            return "expense"
        if any(marker in text for marker in ["情绪", "心情", "状态", "睡眠", "睡得", "压力", "焦虑", "累不累"]):
            return "mood"
        if any(marker in text for marker in ["计划", "待办", "安排", "提醒", "要做", "没处理", "记得"]):
            return "plan"
        if any(marker in text for marker in ["学习", "研究", "技术", "主题", "论文", "架构", "提到", "内容"]):
            return "learning"
        if any(token in lowered for token in ["rag", "agent", "roomos", "langgraph", "pgvector", "workflow", "embedding"]):
            return "learning"
        return None


query_router_service = QueryRouterService()
