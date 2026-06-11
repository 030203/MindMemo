import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Brain, Briefcase, CircleDollarSign, HeartPulse, Lightbulb, ListChecks, MessageSquareText } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { DashboardInsights, InsightSourceItem, MemoryInsightCard } from "../api/types";
import { formatDateTime } from "../utils/presentation";

type InsightTab = "overview" | "expenses" | "reflection";
type SourceFilter = "all" | "memory" | "todo";
type InsightWindow = "default" | "7d" | "30d" | "90d" | "month" | "all";

const insightTabs: Array<{ key: InsightTab; label: string; description: string }> = [
  { key: "overview", label: "总览", description: "跨消费、情绪、学习、计划和项目的当前信号。" },
  { key: "expenses", label: "消费", description: "从结构化消费事实里看金额、频率和异常。" },
  { key: "reflection", label: "复盘", description: "把近期学习、情绪、项目和待办整理成可追溯线索。" },
];

const insightWindows: Array<{ key: InsightWindow; label: string }> = [
  { key: "default", label: "智能默认" },
  { key: "7d", label: "近 7 天" },
  { key: "30d", label: "近 30 天" },
  { key: "90d", label: "近 90 天" },
  { key: "month", label: "本月" },
  { key: "all", label: "全部" },
];

function normalizeTab(value: string | null): InsightTab {
  if (value === "expenses" || value === "reflection") {
    return value;
  }
  return "overview";
}

function normalizeSourceFilter(value: string | null): SourceFilter {
  if (value === "memory" || value === "todo") {
    return value;
  }
  return "all";
}

function normalizeInsightWindow(value: string | null): InsightWindow {
  if (value === "7d" || value === "30d" || value === "90d" || value === "month" || value === "all") {
    return value;
  }
  return "default";
}

function sourceFilterLabel(value: SourceFilter) {
  if (value === "memory") return "只看记忆";
  if (value === "todo") return "只看待办";
  return "全部来源";
}

function filterSources(sources: InsightSourceItem[], sourceFilter: SourceFilter) {
  if (sourceFilter === "all") {
    return sources;
  }
  return sources.filter((source) => source.type === sourceFilter);
}

function updateSearchParams(
  setSearchParams: ReturnType<typeof useSearchParams>[1],
  next: { tab?: InsightTab; card?: string; source?: SourceFilter; window?: InsightWindow },
) {
  setSearchParams((current) => {
    const params = new URLSearchParams(current);
    if (next.tab !== undefined) {
      if (next.tab === "overview") {
        params.delete("tab");
      } else {
        params.set("tab", next.tab);
      }
      params.delete("card");
    }
    if (next.card !== undefined) {
      if (next.card) {
        params.set("card", next.card);
      } else {
        params.delete("card");
      }
    }
    if (next.source !== undefined) {
      if (next.source === "all") {
        params.delete("source");
      } else {
        params.set("source", next.source);
      }
    }
    if (next.window !== undefined) {
      if (next.window === "default") {
        params.delete("window");
      } else {
        params.set("window", next.window);
      }
      params.delete("card");
    }
    return params;
  });
}

function renderInsightIcon(kind: string) {
  if (kind === "expense") return <CircleDollarSign size={18} />;
  if (kind === "mood") return <HeartPulse size={18} />;
  if (kind === "learning") return <Lightbulb size={18} />;
  if (kind === "plan") return <ListChecks size={18} />;
  if (kind === "project") return <Briefcase size={18} />;
  return <Brain size={18} />;
}

function getInsightQuery(tab: InsightTab, window: InsightWindow) {
  if (tab === "expenses") {
    return api.getExpenseInsights(window);
  }
  if (tab === "reflection") {
    return api.getReflectionInsights(window);
  }
  return api.getInsightOverview(window);
}

function InsightSourceList({ card, sourceFilter }: { card: MemoryInsightCard; sourceFilter: SourceFilter }) {
  const sources = filterSources(card.sources, sourceFilter);

  if (sources.length === 0) {
    return (
      <div className="empty-state insight-empty-sources">
        {card.sources.length === 0 ? "这张卡片暂时没有可回跳的来源。" : `当前筛选下没有${sourceFilterLabel(sourceFilter)}。`}
      </div>
    );
  }

  return (
    <div className="insight-detail-sources">
      {sources.map((source) => {
        const to = source.type === "memory" ? `/memories/${source.id}` : "/todos";
        return (
          <Link className="insight-detail-source" key={`${card.kind}-${source.type}-${source.id}`} to={to}>
            <div>
              <span>{source.type === "memory" ? "记忆来源" : "待办来源"}</span>
              <strong>{source.title}</strong>
            </div>
            <p>{source.snippet}</p>
            <div className="inline-meta">
              <span>{formatDateTime(source.event_time)}</span>
              <ArrowRight size={14} />
            </div>
          </Link>
        );
      })}
    </div>
  );
}

function InsightCardDetail({ card, sourceFilter }: { card: MemoryInsightCard; sourceFilter: SourceFilter }) {
  return (
    <article className={`insight-detail-card insight-card-${card.tone}`}>
      <div className="insight-detail-header">
        <div className="insight-topline">
          <span className="insight-icon">{renderInsightIcon(card.kind)}</span>
          <span>{card.title}</span>
        </div>
        <Link className="button-ghost insight-question-link" to={{ pathname: "/chat", search: `?q=${encodeURIComponent(card.question)}` }}>
          <MessageSquareText size={15} />
          追问
        </Link>
      </div>

      <div className="insight-detail-body">
        <strong>{card.value}</strong>
        <p>{card.detail}</p>
      </div>

      {card.items.length > 0 ? (
        <div className="insight-items insight-detail-items">
          {card.items.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
      ) : null}

      <InsightSourceList card={card} sourceFilter={sourceFilter} />
    </article>
  );
}

export function InsightsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = normalizeTab(searchParams.get("tab"));
  const activeCardKind = searchParams.get("card") ?? "";
  const sourceFilter = normalizeSourceFilter(searchParams.get("source"));
  const activeWindow = normalizeInsightWindow(searchParams.get("window"));
  const activeTabMeta = insightTabs.find((item) => item.key === activeTab) ?? insightTabs[0];

  const { data, isLoading, error } = useQuery<DashboardInsights>({
    queryKey: ["insights", activeTab, activeWindow],
    queryFn: () => getInsightQuery(activeTab, activeWindow),
  });
  const {
    data: focusedCard,
    isLoading: focusedCardLoading,
    error: focusedCardError,
  } = useQuery<MemoryInsightCard>({
    queryKey: ["insight-card", activeCardKind, activeWindow],
    queryFn: () => api.getInsightCard(activeCardKind, activeWindow),
    enabled: Boolean(activeCardKind),
  });

  const cards = data?.cards ?? [];
  const fallbackFocusedCards = activeCardKind ? cards.filter((card) => card.kind === activeCardKind) : cards;
  const visibleCards = activeCardKind && focusedCard ? [focusedCard] : fallbackFocusedCards;
  const stats = useMemo(
    () => ({
      cards: visibleCards.length,
      sources: visibleCards.reduce((total, card) => total + filterSources(card.sources, sourceFilter).length, 0),
      questions: visibleCards.filter((card) => card.question.trim()).length,
    }),
    [sourceFilter, visibleCards],
  );

  return (
    <div className="page-grid">
      <section className="panel insight-hero-panel">
        <div className="section-title">
          <div>
            <span className="eyebrow">Phase 12 Insight Agents</span>
            <h3>把个人事实整理成可追溯洞察</h3>
          </div>
          <Link className="button-ghost" to="/chat">
            <MessageSquareText size={15} />
            问 AI
          </Link>
        </div>
        <p className="panel-subtitle">
          当前页面直接消费独立 Insight API。每张卡片都保留来源回链，方便从结论跳回原始记忆或待办证据。
        </p>
        <div className="insight-summary-grid">
          <div className="trace-stat">
            <span>洞察卡片</span>
            <strong>{stats.cards}</strong>
          </div>
          <div className="trace-stat">
            <span>来源证据</span>
            <strong>{stats.sources}</strong>
          </div>
          <div className="trace-stat">
            <span>可追问问题</span>
            <strong>{stats.questions}</strong>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="section-title insight-toolbar">
          <div>
            <h3>{activeTabMeta.label}洞察</h3>
            <p className="panel-subtitle">{activeTabMeta.description}</p>
          </div>
          <div className="segmented-control" role="tablist" aria-label="洞察分类">
            {insightTabs.map((item) => (
              <button
                className={item.key === activeTab ? "active" : ""}
                key={item.key}
                type="button"
                onClick={() => updateSearchParams(setSearchParams, { tab: item.key })}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        {cards.length > 0 ? (
          <div className="insight-filter-panel">
            <div className="insight-filter-group">
              <span>洞察卡片</span>
              <div className="insight-chip-row" role="list" aria-label="单张洞察筛选">
                <button className={`signal-filter-chip${!activeCardKind ? " active" : ""}`} type="button" onClick={() => updateSearchParams(setSearchParams, { card: "" })}>
                  全部
                </button>
                {cards.map((card) => (
                  <button
                    className={`signal-filter-chip${activeCardKind === card.kind ? " active" : ""}`}
                    key={card.kind}
                    type="button"
                    onClick={() => updateSearchParams(setSearchParams, { card: card.kind })}
                  >
                    {card.title}
                  </button>
                ))}
              </div>
            </div>

            <div className="insight-filter-group">
              <span>来源类型</span>
              <div className="segmented-control" role="tablist" aria-label="来源类型筛选">
                {(["all", "memory", "todo"] as SourceFilter[]).map((item) => (
                  <button
                    className={item === sourceFilter ? "active" : ""}
                    key={item}
                    type="button"
                    onClick={() => updateSearchParams(setSearchParams, { source: item })}
                  >
                    {sourceFilterLabel(item)}
                  </button>
                ))}
              </div>
            </div>

            <div className="insight-filter-group">
              <span>时间窗口</span>
              <div className="segmented-control insight-window-control" role="tablist" aria-label="洞察时间窗口">
                {insightWindows.map((item) => (
                  <button
                    className={item.key === activeWindow ? "active" : ""}
                    key={item.key}
                    type="button"
                    onClick={() => updateSearchParams(setSearchParams, { window: item.key })}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : null}

        {isLoading || focusedCardLoading ? <div className="loading">正在读取洞察...</div> : null}
        {error ? <div className="error">洞察加载失败，请确认后端服务已经启动。</div> : null}
        {focusedCardError ? <div className="error">单张洞察加载失败，已保留列表结果作为兜底。</div> : null}
        {!isLoading && !error && cards.length === 0 ? (
          <div className="empty-state">暂时没有足够的结构化事实生成洞察。继续记录消费、学习、项目或复盘内容后再回来看看。</div>
        ) : null}

        <div className="insight-detail-grid">
          {visibleCards.map((card) => (
            <InsightCardDetail card={card} key={card.kind} sourceFilter={sourceFilter} />
          ))}
        </div>
      </section>
    </div>
  );
}
