import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { CitationItem, CitationScoreBreakdown, QARequest, RetrievalTraceCandidate, RetrievalTraceResponse } from "../api/types";
import { formatCitationStrength, formatDateTime, formatQAModeLabel } from "../utils/presentation";

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  mode?: QARequest["mode"];
  citations?: CitationItem[];
  followups?: string[];
  trace?: RetrievalTraceResponse | null;
};

type CandidateHitGroup = {
  memoryId: string;
  primary: RetrievalTraceCandidate;
  hits: RetrievalTraceCandidate[];
  rankRangeLabel: string;
  extraSnippets: string[];
};

type CandidateFunnel = {
  rawChunks: number;
  uniqueMemories: number;
  enteredDirectWindow: number;
  enteredRerank: number;
  finalSelected: number;
  relationOnlySelected: number;
  relationRecovered: number;
};

type WorkflowStep = {
  key: string;
  label: string;
  status: string;
  detail: string;
  metric?: string;
  durationMs?: number;
  errorMessage?: string;
  metadata?: Record<string, unknown>;
};

type ExecutionPlan = {
  plannerVersion: string;
  summary: string;
  route: string;
  intent: string;
  mode: string;
  subquestions: Array<{
    question: string;
    tool: string;
    reason: string;
  }>;
  tools: string[];
};

const defaultQuestion = "我最近有哪些重要事情？";

const suggestedQuestions = [
  "我最近有哪些重要事情？",
  "我这个月总共花了多少钱？",
  "北京天气怎么样？",
  "联网查一下 Tavily 是什么？",
];

function formatRouteLabel(route: unknown) {
  const normalized = typeof route === "string" ? route : "";
  if (normalized === "fact") return "结构化事实";
  if (normalized === "weather") return "天气工具";
  if (normalized === "web") return "联网搜索";
  if (normalized === "memory") return "记忆检索";
  if (normalized === "direct") return "直接回答";
  if (normalized === "clarify") return "澄清问题";
  return normalized || "未标注";
}

function formatIntentLabel(intent: unknown) {
  const normalized = typeof intent === "string" ? intent : "";
  if (normalized === "general_chat") return "通用闲聊";
  if (normalized === "doc_summary") return "文档总结";
  if (normalized === "doc_extract") return "文档提取";
  if (normalized === "doc_translate") return "文档翻译";
  if (normalized === "doc_rewrite") return "文档改写";
  if (normalized === "doc_rewrite_weekly_report") return "改成周报";
  if (normalized === "doc_rewrite_email") return "改成邮件";
  if (normalized === "plan") return "计划 / 待办";
  if (normalized === "expense") return "消费";
  if (normalized === "mood") return "情绪";
  if (normalized === "learning") return "学习";
  if (normalized === "weather") return "天气";
  if (normalized === "web_search") return "联网搜索";
  if (normalized === "memory_recall") return "记忆回想";
  if (normalized === "open_chat") return "开放闲聊";
  if (normalized === "clarify_scope") return "范围澄清";
  return normalized || "未标注";
}

function formatAnswerSource(source: string) {
  if (source === "memory_rag") return "记忆问答";
  if (source === "fact_insight") return "事实洞察";
  if (source === "weather_tool") return "天气工具";
  if (source === "web_tool") return "联网工具";
  if (source === "direct_answer") return "直接回答";
  if (source === "clarify") return "澄清追问";
  if (source === "weather_tool_unavailable") return "天气工具不可用";
  if (source === "web_tool_unavailable") return "联网工具不可用";
  return source;
}

function formatRetrievalScope(scope: unknown) {
  const normalized = typeof scope === "string" ? scope : "";
  if (normalized === "none") return "不检索";
  if (normalized === "active_document") return "当前文档";
  if (normalized === "active_record") return "当前记录";
  if (normalized === "global_kb") return "全局知识库";
  return normalized || "未标注";
}

function formatAnswerMode(mode: unknown) {
  const normalized = typeof mode === "string" ? mode : "";
  if (normalized === "direct_answer") return "直接回答";
  if (normalized === "tool_answer") return "工具回答";
  if (normalized === "clarify") return "澄清";
  if (normalized === "summarize") return "总结";
  if (normalized === "extract") return "提取";
  if (normalized === "transform") return "改写/转换";
  if (normalized === "grounded_qa") return "证据问答";
  if (normalized === "grounded_review") return "上下文分析";
  return normalized || "未标注";
}

function formatRelationType(relationType: unknown) {
  const normalized = typeof relationType === "string" ? relationType : "";
  if (normalized === "shared_fact") return "共享事实";
  if (normalized === "shared_entity") return "共享实体 / 主题";
  if (normalized === "shared_semantic_signal") return "共享语义信号";
  return normalized || "relation";
}

function formatBreakdownSource(source: string) {
  if (source === "relation") return "关系扩展";
  if (source === "direct") return "直接命中";
  if (source === "external") return "外部来源";
  return source;
}

function formatExclusionReason(reason: string | undefined) {
  if (reason === "outside_direct_window") return "没进初筛窗口";
  if (reason === "below_direct_score_floor") return "进入窗口但命中太弱";
  if (reason === "below_final_score_floor") return "综合分太低";
  if (reason === "trimmed_after_rerank") return "重排后未进入前列";
  if (reason === "anchor_only_shortcut") return "锚点直达，其他引用被收起";
  return reason || "未入选";
}

function traceKey(trace: RetrievalTraceResponse | null | undefined) {
  return trace?.id ?? "";
}

function getRelationExpansions(trace: RetrievalTraceResponse) {
  return Array.isArray(trace.metadata.related_memory_expansions)
    ? (trace.metadata.related_memory_expansions as Array<Record<string, unknown>>)
    : [];
}

function getCitationBreakdowns(trace: RetrievalTraceResponse) {
  return Array.isArray(trace.metadata.citation_score_breakdown)
    ? (trace.metadata.citation_score_breakdown as CitationScoreBreakdown[])
    : [];
}

function getEffectiveQuestion(trace: RetrievalTraceResponse) {
  return typeof trace.metadata.effective_question === "string" ? trace.metadata.effective_question.trim() : "";
}

function wasConversationContextUsed(trace: RetrievalTraceResponse) {
  return trace.metadata.conversation_context_used === true;
}

function getAgentRunId(trace: RetrievalTraceResponse) {
  return typeof trace.metadata.agent_run_id === "string" ? trace.metadata.agent_run_id : "";
}

function getAgentRunStatus(trace: RetrievalTraceResponse) {
  return typeof trace.metadata.agent_run_status === "string" ? trace.metadata.agent_run_status : "";
}

function getAgentRunDurationMs(trace: RetrievalTraceResponse) {
  return typeof trace.metadata.agent_run_duration_ms === "number" ? trace.metadata.agent_run_duration_ms : null;
}

function getAgentRunErrorMessage(trace: RetrievalTraceResponse) {
  return typeof trace.metadata.agent_run_error_message === "string" ? trace.metadata.agent_run_error_message : "";
}

function getExecutionPlan(trace: RetrievalTraceResponse): ExecutionPlan | null {
  const raw = trace.metadata.execution_plan;
  if (!raw || typeof raw !== "object") {
    return null;
  }
  const plan = raw as Record<string, unknown>;
  const subquestions = Array.isArray(plan.subquestions)
    ? plan.subquestions
        .map((item) => {
          if (typeof item === "string") {
            return { question: item, tool: "", reason: "" };
          }
          if (!item || typeof item !== "object") {
            return null;
          }
          const row = item as Record<string, unknown>;
          return {
            question: typeof row.question === "string" ? row.question : "",
            tool: typeof row.tool === "string" ? row.tool : "",
            reason: typeof row.reason === "string" ? row.reason : "",
          };
        })
        .filter(
          (
            item,
          ): item is {
            question: string;
            tool: string;
            reason: string;
          } => Boolean(item?.question),
        )
    : [];
  const tools = Array.isArray(plan.tools) ? plan.tools.filter((item): item is string => typeof item === "string") : [];
  return {
    plannerVersion: typeof plan.planner_version === "string" ? plan.planner_version : "",
    summary: typeof plan.summary === "string" ? plan.summary : "",
    route: typeof plan.route === "string" ? plan.route : "",
    intent: typeof plan.intent === "string" ? plan.intent : "",
    mode: typeof plan.mode === "string" ? plan.mode : "",
    subquestions,
    tools,
  };
}

function getWorkflowSteps(trace: RetrievalTraceResponse) {
  if (!Array.isArray(trace.metadata.workflow_steps)) {
    return [];
  }

  return trace.metadata.workflow_steps
    .map((item): WorkflowStep | null => {
      if (!item || typeof item !== "object") {
        return null;
      }
      const row = item as Record<string, unknown>;
      return {
        key: typeof row.key === "string" ? row.key : crypto.randomUUID(),
        label: typeof row.label === "string" ? row.label : "未命名步骤",
        status: typeof row.status === "string" ? row.status : "done",
        detail: typeof row.detail === "string" ? row.detail : "",
        metric: typeof row.metric === "string" ? row.metric : undefined,
        durationMs: typeof row.duration_ms === "number" ? row.duration_ms : undefined,
        errorMessage: typeof row.error_message === "string" ? row.error_message : undefined,
        metadata: row.metadata && typeof row.metadata === "object" ? (row.metadata as Record<string, unknown>) : undefined,
      };
    })
    .filter((item): item is WorkflowStep => Boolean(item));
}

function formatWorkflowStatus(status: string) {
  if (status === "failed" || status === "error") return "失败";
  if (status === "running") return "执行中";
  if (status === "pending") return "等待中";
  if (status === "completed" || status === "done") return "完成";
  return status || "未知";
}

function formatDurationMs(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "";
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(2)}s`;
  }
  return `${Math.round(value)}ms`;
}

function scoreTag(label: string, value: number) {
  return (
    <span className="trace-score-tag" key={label}>
      <span>{label}</span>
      <strong>{value.toFixed(2)}</strong>
    </span>
  );
}

function textTag(label: string, value: string) {
  return (
    <span className="trace-score-tag" key={`${label}-${value}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </span>
  );
}

function formatRankRange(ranks: number[]) {
  if (ranks.length === 0) return "-";
  if (ranks.length === 1) return `#${ranks[0]}`;
  return `#${ranks[0]}-#${ranks[ranks.length - 1]}`;
}

function groupCandidateHits(candidates: RetrievalTraceCandidate[]) {
  const groups = new Map<string, CandidateHitGroup>();
  for (const candidate of candidates) {
    const existing = groups.get(candidate.memory_id);
    if (!existing) {
      groups.set(candidate.memory_id, {
        memoryId: candidate.memory_id,
        primary: candidate,
        hits: [candidate],
        rankRangeLabel: `#${candidate.rank}`,
        extraSnippets: [],
      });
      continue;
    }
    existing.hits.push(candidate);
  }

  return Array.from(groups.values()).map((group) => {
    const ranks = group.hits.map((item) => item.rank).sort((left, right) => left - right);
    const extraSnippets = Array.from(
      new Set(
        group.hits
          .slice(1)
          .map((item) => item.snippet.trim())
          .filter((snippet) => snippet && snippet !== group.primary.snippet.trim()),
      ),
    ).slice(0, 2);
    return {
      ...group,
      rankRangeLabel: formatRankRange(ranks),
      extraSnippets,
    };
  });
}

function buildCandidateFunnel(candidateGroups: CandidateHitGroup[], selectedCitations: CitationItem[]): CandidateFunnel {
  const selectedHitMemoryIds = new Set(candidateGroups.filter((group) => group.primary.final_selected).map((group) => group.memoryId));
  const selectedMemoryCitationIds = new Set(selectedCitations.filter((citation) => citation.type === "memory").map((citation) => citation.id));
  let relationOnlySelected = 0;
  for (const memoryId of selectedMemoryCitationIds) {
    if (!selectedHitMemoryIds.has(memoryId)) {
      relationOnlySelected += 1;
    }
  }

  return {
    rawChunks: candidateGroups.reduce((total, group) => total + group.hits.length, 0),
    uniqueMemories: candidateGroups.length,
    enteredDirectWindow: candidateGroups.filter((group) => group.primary.entered_direct_window === true).length,
    enteredRerank: candidateGroups.filter((group) => group.primary.entered_rerank === true).length,
    finalSelected: selectedHitMemoryIds.size,
    relationOnlySelected,
    relationRecovered: candidateGroups.filter((group) => group.primary.final_selected && group.primary.citation_source === "relation").length,
  };
}

function summarizeCandidate(candidate: RetrievalTraceCandidate) {
  if (candidate.final_selected) {
    if (candidate.citation_source === "relation" && candidate.entered_direct_window === false) {
      return "这条 direct hit 自己没进初筛窗口，但所属记忆被关系扩展重新带回，并最终入选。";
    }
    return `这条 hit 所属记忆进入重排，并以${formatBreakdownSource(candidate.citation_source ?? "direct")}身份保留到最终引用。`;
  }
  if (candidate.exclusion_reason_detail) {
    return `${formatExclusionReason(candidate.exclusion_reason ?? undefined)}：${candidate.exclusion_reason_detail}`;
  }
  if (candidate.entered_direct_window === false) {
    return "这条 hit 停在 direct window 之外，没有进入后续重排。";
  }
  if (candidate.entered_rerank === false) {
    return "这条 hit 进入了 direct window，但对应记忆没有进入 rerank。";
  }
  return "";
}

function CandidateHitCard({ group }: { group: CandidateHitGroup }) {
  const candidate = group.primary;
  const hasDecisionData =
    candidate.entered_direct_window !== undefined ||
    candidate.entered_rerank !== undefined ||
    candidate.final_selected !== undefined ||
    typeof candidate.final_score === "number";
  const summary = summarizeCandidate(candidate);

  return (
    <div className={`trace-item${candidate.final_selected === false ? " trace-item-muted" : ""}`}>
      <div className="trace-item-topline">
        <strong>
          {group.rankRangeLabel} {candidate.title}
        </strong>
        <span>
          {candidate.category} · {formatCitationStrength(candidate.score)}
        </span>
      </div>
      <p>{candidate.snippet}</p>
      {hasDecisionData ? (
        <div className="trace-explanation-grid">
          <div className="trace-score-tags">
            {textTag("命中片段", `${group.hits.length} 个`)}
            {scoreTag("检索分", candidate.raw_hit_score ?? candidate.score)}
            {typeof candidate.normalized_hit_score === "number" ? scoreTag("归一分", candidate.normalized_hit_score) : null}
            {textTag("初筛窗口", candidate.entered_direct_window === undefined ? "未标注" : candidate.entered_direct_window ? "进入" : "未进")}
            {textTag("重排", candidate.entered_rerank === undefined ? "未标注" : candidate.entered_rerank ? "进入" : "未进")}
            {textTag("最终", candidate.final_selected === undefined ? "未标注" : candidate.final_selected ? "入选" : "落选")}
            {typeof candidate.final_score === "number" ? scoreTag("最终分", candidate.final_score) : null}
          </div>
          {summary ? <div className="trace-subtle">{summary}</div> : null}
          {group.hits.length > 1 ? (
            <div className="trace-subtle">
              这条记忆共命中 {group.hits.length} 个片段，分布在 {group.rankRangeLabel}。这里展示最靠前的一条命中。
            </div>
          ) : null}
          {group.extraSnippets.length > 0 ? (
            <div className="trace-snippet-stack">
              {group.extraSnippets.map((snippet, index) => (
                <div className="trace-subtle" key={`${group.memoryId}-extra-${index}`}>
                  其他命中片段：{snippet}
                </div>
              ))}
            </div>
          ) : null}
          <Link className="trace-inline-link" to={`/app/memories/${candidate.memory_id}`}>
            打开这条原始记录
          </Link>
        </div>
      ) : null}
    </div>
  );
}

function CitationBreakdownCard({
  citation,
  breakdown,
}: {
  citation: CitationItem;
  breakdown: CitationScoreBreakdown | undefined;
}) {
  return (
    <div className="trace-item">
      <div className="trace-item-topline">
        <strong>{citation.title}</strong>
        <span>{citation.type === "weather" ? "实时天气" : formatCitationStrength(citation.score)}</span>
      </div>
      <p>{citation.snippet}</p>

      {breakdown ? (
        <div className="trace-explanation-grid">
          <div className="trace-ranking-note">
            <strong>排序解释</strong>
            <span>
              {formatBreakdownSource(breakdown.source)} · 最终分 {breakdown.final_score.toFixed(2)}
            </span>
          </div>
          <div className="trace-score-tags">
            {scoreTag("直接命中", breakdown.direct_score)}
            {scoreTag("关系补强", breakdown.relation_score)}
            {scoreTag("时间新近", breakdown.recency_score)}
            {scoreTag("事实置信", breakdown.fact_score)}
            {scoreTag("附加加成", breakdown.source_bonus)}
          </div>
          {breakdown.relation_reason ? <div className="trace-subtle">{breakdown.relation_reason}</div> : null}
          {breakdown.category || breakdown.event_time ? (
            <div className="trace-subtle">
              {[breakdown.category || null, breakdown.event_time ? formatDateTime(breakdown.event_time) : null].filter(Boolean).join(" · ")}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function RejectedBreakdownCard({ breakdown }: { breakdown: CitationScoreBreakdown }) {
  return (
    <div className="trace-item trace-item-muted">
      <div className="trace-item-topline">
        <strong>{breakdown.title}</strong>
        <span>{formatExclusionReason(breakdown.exclusion_reason)}</span>
      </div>
      {breakdown.snippet ? <p>{breakdown.snippet}</p> : null}
      <div className="trace-explanation-grid">
        <div className="trace-ranking-note">
          <strong>落选原因</strong>
          <span>{formatBreakdownSource(breakdown.source)}</span>
        </div>
        <div className="trace-score-tags">
          {typeof breakdown.direct_hit_rank === "number" ? (
            <span className="trace-score-tag">
              <span>直接命中名次</span>
              <strong>#{breakdown.direct_hit_rank}</strong>
            </span>
          ) : null}
          {scoreTag("直接命中", breakdown.direct_score)}
          {scoreTag("关系补强", breakdown.relation_score)}
          {scoreTag("时间新近", breakdown.recency_score)}
          {scoreTag("事实置信", breakdown.fact_score)}
          {scoreTag("最终分", breakdown.final_score)}
        </div>
        {breakdown.exclusion_reason_detail ? <div className="trace-subtle">{breakdown.exclusion_reason_detail}</div> : null}
      </div>
    </div>
  );
}

function CandidateFunnelCard({ funnel }: { funnel: CandidateFunnel }) {
  return (
    <div className="trace-explanation-grid">
      <div className="trace-score-tags">
        {textTag("原始片段", `${funnel.rawChunks} 个`)}
        {textTag("候选记忆", `${funnel.uniqueMemories} 条`)}
        {textTag("进初筛", `${funnel.enteredDirectWindow} 条`)}
        {textTag("进重排", `${funnel.enteredRerank} 条`)}
        {textTag("命中入选", `${funnel.finalSelected} 条`)}
        {textTag("关系补入", `${funnel.relationOnlySelected} 条`)}
      </div>
      <div className="trace-subtle">
        漏斗从 raw chunk 命中开始，先按记忆去重，再进入 direct window 和 rerank。最终引用里，另有关系扩展补入的记忆会单独计数。
      </div>
      {funnel.relationRecovered > 0 ? (
        <div className="trace-subtle">其中有 {funnel.relationRecovered} 条 direct hit 虽然不是纯 direct 路径入选，但被关系扩展重新补回了最终引用。</div>
      ) : null}
    </div>
  );
}

function RetrievalTraceCard({
  trace,
  title,
  subtitle,
}: {
  trace: RetrievalTraceResponse | null | undefined;
  title: string;
  subtitle?: string;
}) {
  if (!trace) {
    return (
      <div className="trace-panel empty">
        <strong>{title}</strong>
        <p>{subtitle ?? "这条回答还没有可展示的检索轨迹。"}</p>
      </div>
    );
  }

  const route = trace.metadata.query_route;
  const intent = trace.metadata.query_intent;
  const routeReason = typeof trace.metadata.query_route_reason === "string" ? trace.metadata.query_route_reason : "";
  const retrievalScope = trace.metadata.retrieval_scope;
  const answerMode = trace.metadata.answer_mode;
  const effectiveQuestion = getEffectiveQuestion(trace);
  const contextUsed = wasConversationContextUsed(trace);
  const agentRunId = getAgentRunId(trace);
  const agentRunStatus = getAgentRunStatus(trace);
  const agentRunDurationMs = getAgentRunDurationMs(trace);
  const agentRunErrorMessage = getAgentRunErrorMessage(trace);
  const executionPlan = getExecutionPlan(trace);
  const rerankStrategy =
    typeof trace.metadata.citation_rerank_strategy === "string" ? trace.metadata.citation_rerank_strategy : "";
  const relatedCount =
    typeof trace.metadata.related_memory_count === "number" ? trace.metadata.related_memory_count : 0;
  const relationExpansions = getRelationExpansions(trace);
  const citationBreakdowns = getCitationBreakdowns(trace);
  const workflowSteps = getWorkflowSteps(trace);
  const rejectedBreakdowns = citationBreakdowns.filter((item) => item.selected === false);
  const breakdownByMemoryId = new Map(citationBreakdowns.map((item) => [item.memory_id, item]));
  const candidateGroups = groupCandidateHits(trace.candidates);
  const candidateFunnel = buildCandidateFunnel(candidateGroups, trace.selected_citations);

  return (
    <div className="trace-panel">
      <div className="trace-header">
        <div>
          <strong>{title}</strong>
          <p>{subtitle ?? "看一下这次回答是怎么检索、扩展、再重排到最终引用的。"}</p>
        </div>
        <span className="trace-time">{formatDateTime(trace.created_at)}</span>
      </div>

      <div className="trace-pill-row">
        <span className="trace-pill">{formatRouteLabel(route)}</span>
        <span className="trace-pill">{formatIntentLabel(intent)}</span>
        <span className="trace-pill">{formatRetrievalScope(retrievalScope)}</span>
        <span className="trace-pill">{formatAnswerMode(answerMode)}</span>
        <span className="trace-pill">{trace.retrieval_strategy}</span>
        <span className="trace-pill">{formatAnswerSource(trace.answer_source)}</span>
        {contextUsed ? <span className="trace-pill trace-pill-context">使用追问上下文</span> : null}
        {agentRunId ? <span className="trace-pill trace-pill-context">已记录 Agent Run</span> : null}
      </div>

      {routeReason ? <div className="trace-note">{routeReason}</div> : null}

      {contextUsed && effectiveQuestion ? (
        <div className="trace-rewrite-panel">
          <div className="trace-rewrite-row">
            <span>原始问题</span>
            <strong>{trace.question}</strong>
          </div>
          <div className="trace-rewrite-row">
            <span>检索问题</span>
            <strong>{effectiveQuestion}</strong>
          </div>
        </div>
      ) : null}

      <div className="trace-stats">
        <div className="trace-stat">
          <span>候选片段</span>
          <strong>{trace.candidates.length}</strong>
        </div>
        <div className="trace-stat">
          <span>候选记忆</span>
          <strong>{candidateGroups.length}</strong>
        </div>
        <div className="trace-stat">
          <span>最终引用</span>
          <strong>{trace.selected_citations.length}</strong>
        </div>
        <div className="trace-stat">
          <span>关系扩展</span>
          <strong>{relatedCount}</strong>
        </div>
        <div className="trace-stat">
          <span>重排策略</span>
          <strong>{rerankStrategy || "未标注"}</strong>
        </div>
      </div>

      {executionPlan ? (
        <div className="trace-section">
          <div className="trace-section-title">执行计划</div>
          <div className="trace-plan-card">
            {executionPlan.summary ? <p className="trace-plan-summary">{executionPlan.summary}</p> : null}
            <div className="trace-score-tags">
              {executionPlan.plannerVersion ? textTag("Planner", executionPlan.plannerVersion) : null}
              {executionPlan.route ? textTag("Route", executionPlan.route) : null}
              {executionPlan.intent ? textTag("Intent", executionPlan.intent) : null}
              {typeof retrievalScope === "string" ? textTag("Retrieval Scope", formatRetrievalScope(retrievalScope)) : null}
              {typeof answerMode === "string" ? textTag("Answer Mode", formatAnswerMode(answerMode)) : null}
            </div>
            {executionPlan.subquestions.length > 0 ? (
              <div className="trace-plan-block">
                <strong>子问题</strong>
                <ol className="trace-plan-list">
                  {executionPlan.subquestions.map((item, index) => (
                    <li key={`subquestion-${index}`}>
                      <span>{item.question}</span>
                      {item.tool ? <code>{item.tool}</code> : null}
                      {item.reason ? <small>{item.reason}</small> : null}
                    </li>
                  ))}
                </ol>
              </div>
            ) : null}
            {executionPlan.tools.length > 0 ? (
              <div className="trace-plan-block">
                <strong>工具选择</strong>
                <div className="trace-pill-row">
                  {executionPlan.tools.map((tool) => (
                    <span className="trace-pill" key={tool}>
                      {tool}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      ) : null}

      {workflowSteps.length > 0 ? (
        <div className="trace-section">
          <div className="trace-section-title">Agent 工作流</div>
          {agentRunId ? (
            <div className="trace-workflow-summary">
              <div className="trace-score-tags">
                {textTag("Run", agentRunId.slice(0, 8))}
                {textTag("状态", formatWorkflowStatus(agentRunStatus || "completed"))}
                {agentRunDurationMs !== null ? textTag("总耗时", formatDurationMs(agentRunDurationMs)) : null}
              </div>
              {agentRunErrorMessage ? <div className="trace-workflow-error">{agentRunErrorMessage}</div> : null}
            </div>
          ) : null}
          <div className="trace-workflow-list">
            {workflowSteps.map((step, index) => (
              <div
                className={`trace-workflow-step${
                  step.status === "failed" || step.status === "error" ? " trace-workflow-step-failed" : ""
                }`}
                key={`${step.key}-${index}`}
              >
                <div className="trace-workflow-marker">{index + 1}</div>
                <div>
                  <div className="trace-workflow-title">
                    <strong>{step.label}</strong>
                    <div className="trace-workflow-meta">
                      <span>{formatWorkflowStatus(step.status)}</span>
                      {step.metric ? <span>{step.metric}</span> : null}
                      {step.durationMs !== undefined ? <span>{formatDurationMs(step.durationMs)}</span> : null}
                    </div>
                  </div>
                  {step.detail ? <p>{step.detail}</p> : null}
                  {step.errorMessage ? <div className="trace-workflow-error">{step.errorMessage}</div> : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {trace.candidates.length > 0 ? (
        <div className="trace-section">
          <div className="trace-section-title">候选命中</div>
          <div className="trace-subtle">
            相同记忆的多条 chunk 命中会折叠在一起，默认展示排位最高的那一条。
          </div>
          <CandidateFunnelCard funnel={candidateFunnel} />
          <div className="trace-list">
            {candidateGroups.map((group) => (
              <CandidateHitCard group={group} key={group.memoryId} />
            ))}
          </div>
        </div>
      ) : null}

      {relationExpansions.length > 0 ? (
        <div className="trace-section">
          <div className="trace-section-title">关系扩展</div>
          <div className="trace-list">
            {relationExpansions.map((item, index) => (
              <div className="trace-item" key={`${String(item.memory_id)}-${index}`}>
                <div className="trace-item-topline">
                  <strong>{String(item.title ?? "未命名记录")}</strong>
                  <span>
                    {formatRelationType(item.relation_type)} · {String(item.score ?? "-")}
                  </span>
                </div>
                <p>{String(item.ranking_reason ?? item.relation_reason ?? "来自相关记忆扩展。")}</p>
                <div className="trace-subtle">
                  来源锚点：{String(item.source_memory_title ?? "未命名记录")}
                  {typeof item.direct_hit_rank === "number" ? ` · 同时也是直接命中第 ${item.direct_hit_rank} 名` : ""}
                  {typeof item.direct_hit_score === "number" ? ` · 直接命中分 ${Number(item.direct_hit_score).toFixed(2)}` : ""}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {trace.selected_citations.length > 0 ? (
        <div className="trace-section">
          <div className="trace-section-title">最终引用与排序解释</div>
          <div className="trace-list">
            {trace.selected_citations.map((citation, index) => (
              <CitationBreakdownCard
                citation={citation}
                breakdown={citation.type === "memory" ? breakdownByMemoryId.get(citation.id) : undefined}
                key={`${citation.type}-${citation.id}-${index}`}
              />
            ))}
          </div>
        </div>
      ) : null}

      {rejectedBreakdowns.length > 0 ? (
        <div className="trace-section">
          <div className="trace-section-title">落选候选</div>
          <div className="trace-list">
            {rejectedBreakdowns.map((breakdown) => (
              <RejectedBreakdownCard breakdown={breakdown} key={`rejected-${breakdown.memory_id}`} />
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function ChatPage() {
  const [searchParams] = useSearchParams();
  const [mode, setMode] = useState<QARequest["mode"]>("memory_only");
  const [question, setQuestion] = useState(defaultQuestion);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [selectedTraceId, setSelectedTraceId] = useState<string>("");

  const { data: recentTraces = [] } = useQuery({
    queryKey: ["retrieval-traces"],
    queryFn: () => api.listRetrievalTraces(12),
  });

  useEffect(() => {
    const presetQuestion = searchParams.get("q");
    if (presetQuestion?.trim()) {
      setQuestion(presetQuestion.trim());
    }
  }, [searchParams]);

  const askQuestion = useMutation({
    mutationFn: api.askQuestion,
    onMutate: (variables) => {
      setPendingQuestion(variables.question);
    },
    onSuccess: (data, variables) => {
      setPendingQuestion(null);
      setMessages((prev) => [
        ...prev,
        { role: "user", content: variables.question, mode: variables.mode },
        {
          role: "assistant",
          content: data.answer,
          mode: variables.mode,
          citations: data.citations,
          followups: data.suggested_followups,
          trace: data.trace,
        },
      ]);
      if (data.trace?.id) {
        setSelectedTraceId(data.trace.id);
      }
      setQuestion("");
    },
    onError: (error, variables) => {
      const failureMessage = error instanceof Error ? error.message : "这次没有整理成功，你可以再问我一次。";
      setPendingQuestion(null);
      setMessages((prev) => [
        ...prev,
        { role: "user", content: variables.question, mode: variables.mode },
        {
          role: "assistant",
          content: `刚刚没有成功整理出来：${failureMessage}`,
          mode: variables.mode,
        },
      ]);
    },
  });

  function submitQuestion(nextQuestion: string, nextMode = mode) {
    const trimmed = nextQuestion.trim();
    if (!trimmed || askQuestion.isPending) {
      return;
    }

    askQuestion.mutate({
      question: trimmed,
      mode: nextMode,
      conversation_context: messages.slice(-4).map((message) => ({
        role: message.role,
        content: message.content,
      })),
    });
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    submitQuestion(question);
  }

  const messageTraces = useMemo(
    () =>
      messages
        .filter((message): message is ChatMessage & { trace: RetrievalTraceResponse } => Boolean(message.trace?.id))
        .map((message) => message.trace),
    [messages],
  );

  const mergedTraces = useMemo(() => {
    const byId = new Map<string, RetrievalTraceResponse>();
    for (const trace of recentTraces) {
      byId.set(trace.id, trace);
    }
    for (const trace of messageTraces) {
      byId.set(trace.id, trace);
    }
    return Array.from(byId.values()).sort((left, right) => right.created_at.localeCompare(left.created_at));
  }, [messageTraces, recentTraces]);

  useEffect(() => {
    if (!selectedTraceId && mergedTraces[0]?.id) {
      setSelectedTraceId(mergedTraces[0].id);
    }
  }, [mergedTraces, selectedTraceId]);

  const selectedTrace = mergedTraces.find((trace) => trace.id === selectedTraceId) ?? messageTraces.at(-1) ?? null;

  return (
    <div className="page-grid">
      <section className="panel">
        <div className="section-title">
          <h3>像聊天一样问我</h3>
          <span className="muted">{formatQAModeLabel(mode)}</span>
        </div>
        <p className="panel-subtitle">你不用记关键词。只要像平时说话一样问，我会从个人记忆、结构化事实和外部工具里整理答案。</p>

        <div className="capture-modes" role="tablist" aria-label="问答模式">
          <button className={`mode-chip${mode === "memory_only" ? " active" : ""}`} type="button" onClick={() => setMode("memory_only")}>
            只看我的记录
          </button>
          <button className={`mode-chip${mode === "hybrid_web" ? " active" : ""}`} type="button" onClick={() => setMode("hybrid_web")}>
            记录 + 联网
          </button>
        </div>

        <div className="soft-note qa-mode-note">
          {mode === "memory_only" ? "适合回想记录、计划、消费、学习内容和时间线。" : "会优先调用联网搜索或天气工具，并保留可追溯来源。"}
        </div>

        <form className="form-grid" onSubmit={handleSubmit}>
          <textarea
            className="textarea"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="比如：最近提到 RAG 的内容有哪些？或者联网查一下 Tavily 是什么？"
          />
          <div className="capture-footer">
            <div className="soft-note">{mode === "memory_only" ? "答案会尽量只基于你的长期记忆。" : "外部信息会和你的个人记忆分开标注来源。"}</div>
            <button className="button" type="submit" disabled={askQuestion.isPending || !question.trim()}>
              {askQuestion.isPending ? "正在整理..." : "问一问"}
            </button>
          </div>
        </form>
      </section>

      <div className="chat-layout">
        <section className="panel">
          <div className="section-title">
            <h3>对话记录</h3>
            <span className="muted">{messages.length === 0 && !pendingQuestion ? "还没开始" : `${Math.ceil((messages.length + (pendingQuestion ? 2 : 0)) / 2)} 轮对话`}</span>
          </div>

          <div className="chat-messages">
            {messages.length === 0 && !pendingQuestion ? <div className="empty-state">先问一个问题试试，比如“我最近在研究哪些技术？”</div> : null}

            {messages.map((message, index) => (
              <div className={`message ${message.role}`} key={`${message.role}-${index}`}>
                <div className="message-topline">
                  <div className="message-role">{message.role === "user" ? "你说" : "我帮你整理"}</div>
                  {message.role === "assistant" ? (
                    <span className="answer-badge">
                      {message.citations?.length ? `参考了 ${message.citations.length} 个来源` : formatQAModeLabel(message.mode ?? "memory_only")}
                    </span>
                  ) : null}
                </div>

                <p>{message.content}</p>

                {message.citations && message.citations.length > 0 ? (
                  <div className="citation-list">
                    {message.citations.map((citation) =>
                      citation.type === "memory" ? (
                        <Link className="citation-card citation-link" key={`${citation.type}-${citation.id}-${index}`} to={`/app/memories/${citation.id}`}>
                          <div className="citation-meta">
                            <strong>{citation.title}</strong>
                            <span className="citation-score">{formatCitationStrength(citation.score)}</span>
                          </div>
                          <p>{citation.snippet}</p>
                          <span className="citation-action">查看这条原始记录</span>
                        </Link>
                      ) : citation.type === "todo" ? (
                        <Link className="citation-card citation-link" key={`${citation.type}-${citation.id}-${index}`} to="/todos">
                          <div className="citation-meta">
                            <strong>{citation.title}</strong>
                            <span className="citation-score">{formatCitationStrength(citation.score)}</span>
                          </div>
                          <p>{citation.snippet}</p>
                          <span className="citation-action">查看相关待办</span>
                        </Link>
                      ) : (
                        <div className="citation-card" key={`${citation.type}-${citation.id}-${index}`}>
                          <div className="citation-meta">
                            <strong>{citation.title}</strong>
                            <span className="citation-score">{citation.type === "weather" ? "实时天气" : formatCitationStrength(citation.score)}</span>
                          </div>
                          <p>{citation.snippet}</p>
                          {citation.type === "web" ? (
                            <a className="citation-action" href={citation.id} target="_blank" rel="noreferrer">
                              打开网页来源
                            </a>
                          ) : null}
                        </div>
                      ),
                    )}
                  </div>
                ) : null}

                {message.trace ? (
                  <details className="trace-details">
                    <summary>查看这次检索轨迹</summary>
                    <RetrievalTraceCard trace={message.trace} title="本次回答的检索轨迹" />
                  </details>
                ) : null}

                {message.followups && message.followups.length > 0 ? (
                  <div className="followup-list">
                    {message.followups.map((followup) => (
                      <button key={followup} className="followup-chip" type="button" onClick={() => setQuestion(followup)}>
                        {followup}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}

            {pendingQuestion ? (
              <>
                <div className="message user">
                  <div className="message-topline">
                    <div className="message-role">你说</div>
                  </div>
                  <p>{pendingQuestion}</p>
                </div>
                <div className="message assistant pending">
                  <div className="message-topline">
                    <div className="message-role">我帮你整理</div>
                    <span className="answer-badge">{formatQAModeLabel(mode)}</span>
                  </div>
                  <p>{mode === "memory_only" ? "我正在翻你的记录，整理最相关的内容和来源。" : "我正在调用外部工具，并把结果和来源一起整理出来。"}</p>
                </div>
              </>
            ) : null}
          </div>
        </section>

        <div className="page-grid">
          <section className="panel warm-panel">
            <div className="section-title">
              <h3>最近检索轨迹</h3>
              <span className="muted">{mergedTraces.length} 条</span>
            </div>

            {mergedTraces.length === 0 ? (
              <div className="empty-state">等你问出第一条问题，这里就会开始留下检索轨迹。</div>
            ) : (
              <div className="trace-history-list">
                {mergedTraces.map((trace) => (
                  <button
                    key={trace.id}
                    type="button"
                    className={`trace-history-item${trace.id === traceKey(selectedTrace) ? " active" : ""}`}
                    onClick={() => setSelectedTraceId(trace.id)}
                  >
                    <strong>{trace.question}</strong>
                    <span>
                      {formatRouteLabel(trace.metadata.query_route)} · {formatDateTime(trace.created_at)}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </section>

          <section className="panel">
            <RetrievalTraceCard
              trace={selectedTrace}
              title="检索轨迹详情"
              subtitle="这里会显示路由判断、候选片段、关系扩展，以及每条最终引用为什么会排到前面。"
            />
          </section>

          <section className="panel warm-panel">
            <div className="section-title">
              <h3>你可以这样问</h3>
            </div>
            <div className="soft-prompt-list">
              {suggestedQuestions.map((item) => (
                <button key={item} className="prompt-pill prompt-button" type="button" onClick={() => setQuestion(item)}>
                  {item}
                </button>
              ))}
            </div>

            <div className="guide-list">
              <div className="guide-item">
                <strong>个人记忆</strong>
                <p>适合问最近安排、某个主题的记录、没完成的事，或者某段时间发生了什么。</p>
              </div>
              <div className="guide-item">
                <strong>联网补充</strong>
                <p>适合查新的外部信息、资料背景、实时天气。结果会显示来自网页还是天气 API。</p>
              </div>
              <div className="guide-item">
                <strong>排序解释</strong>
                <p>检索轨迹里现在能看到每条引用的直接命中分、关系补强分、时间新近分和事实置信分。</p>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
