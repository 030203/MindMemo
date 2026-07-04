import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, CalendarDays, Lightbulb, Loader2, RotateCw, Sparkles, TrendingUp } from "lucide-react";
import { api } from "../api/client";
import type { InsightItem } from "../api/types";
import "../styles/insights.css";

const typeOptions = [
  { value: "all", label: "全部", icon: <Sparkles size={13} /> },
  { value: "pattern", label: "学习模式", icon: <TrendingUp size={13} /> },
  { value: "report", label: "周报摘要", icon: <CalendarDays size={13} /> },
  { value: "learning", label: "知识洞察", icon: <Brain size={13} /> },
  { value: "project", label: "项目分析", icon: <Lightbulb size={13} /> },
];

const typeIconMap: Record<string, ReactNode> = {
  pattern: <TrendingUp size={15} />,
  report: <CalendarDays size={15} />,
  learning: <Brain size={15} />,
  project: <Lightbulb size={15} />,
};

function formatInsightIcon(type: string) {
  return typeIconMap[type] ?? <Lightbulb size={15} />;
}

function describeConfidence(score: number) {
  if (score >= 0.85) return "高置信度";
  if (score >= 0.7) return "较高置信度";
  if (score >= 0.5) return "中等置信度";
  return "仅供参考";
}

function confidenceColor(score: number) {
  if (score >= 0.85) return "#4a8c5c";
  if (score >= 0.7) return "#7a8a4a";
  if (score >= 0.5) return "#a69580";
  return "#bbb";
}

export function InsightsPage() {
  const queryClient = useQueryClient();
  const [typeFilter, setTypeFilter] = useState("all");

  const { data, isLoading, error } = useQuery({
    queryKey: ["insights"],
    queryFn: () => api.listInsights(30),
  });

  const generateMutation = useMutation({
    mutationFn: api.generateInsight,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["insights"] });
    },
  });

  const insights: InsightItem[] = data ?? [];

  const filtered = useMemo(
    () => (typeFilter === "all" ? insights : insights.filter((i) => i.insight_type === typeFilter)),
    [insights, typeFilter],
  );

  const typeCounts = useMemo(() => {
    const counts: Record<string, number> = { all: insights.length };
    for (const i of insights) {
      counts[i.insight_type] = (counts[i.insight_type] ?? 0) + 1;
    }
    return counts;
  }, [insights]);

  if (isLoading) {
    return (
      <div className="ip-loading">
        <Loader2 className="spin" size={20} />
        <span>正在加载 AI 洞察...</span>
      </div>
    );
  }

  if (error) {
    return <div className="ip-error">AI 洞察加载失败，请确认后端服务已启动。</div>;
  }

  return (
    <div className="ip-page">
      {/* Hero section */}
      <section className="ip-hero">
        <span className="ip-hero-accent" />
        <div className="ip-hero-content">
          <div className="ip-hero-text">
            <div className="ip-hero-label">
              <Sparkles size={12} />
              <span>Insight Center</span>
            </div>
            <h1>AI 帮你从记忆里发现的规律</h1>
            <p>
              系统定期分析你的记忆库，发现学习模式、知识关联和潜在习惯。
              每次写入新记忆后，后台会自动生成洞察。
            </p>
          </div>
          <div className="ip-hero-stats">
            <div className="ip-stat">
              <span className="ip-stat-num">{insights.length}</span>
              <span className="ip-stat-label">总洞察</span>
            </div>
            <div className="ip-stat">
              <span className="ip-stat-num">{typeCounts.pattern ?? 0}</span>
              <span className="ip-stat-label">学习模式</span>
            </div>
            <div className="ip-stat">
              <span className="ip-stat-num">{typeCounts.learning ?? 0}</span>
              <span className="ip-stat-label">知识洞察</span>
            </div>
            <div className="ip-stat">
              <span className="ip-stat-num">{typeCounts.project ?? 0}</span>
              <span className="ip-stat-label">项目分析</span>
            </div>
          </div>
        </div>
        <div className="ip-hero-action">
          <button
            className="ip-generate-btn"
            type="button"
            disabled={generateMutation.isPending}
            onClick={() => generateMutation.mutate()}
          >
            {generateMutation.isPending ? (
              <>
                <Loader2 className="spin" size={15} />
                正在分析...
              </>
            ) : (
              <>
                <RotateCw size={15} />
                立即生成新洞察
              </>
            )}
          </button>
        </div>
      </section>

      {/* Filter tabs */}
      {insights.length > 0 && (
        <div className="ip-filters">
          {typeOptions.map((option) => {
            const count = typeCounts[option.value] ?? 0;
            return (
              <button
                key={option.value}
                className={`ip-filter-chip${typeFilter === option.value ? " active" : ""}`}
                type="button"
                onClick={() => setTypeFilter(option.value)}
              >
                {option.icon}
                {option.label}
                <span className="ip-filter-count">{count}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Insight cards */}
      <section className="ip-list">
        {filtered.length === 0 ? (
          <div className="ip-empty">
            <Lightbulb size={28} />
            <p>
              {typeFilter !== "all"
                ? `当前筛选下没有"${typeOptions.find((o) => o.value === typeFilter)?.label ?? typeFilter}"类型的洞察。`
                : "还没有生成洞察。写几条记忆后，点击上方按钮让 AI 帮你发现规律。"}
            </p>
          </div>
        ) : (
          <div className="ip-card-grid">
            {filtered.map((item) => (
              <article className={`ip-card ip-card-${item.insight_type}`} key={item.id}>
                <div className="ip-card-top">
                  <span className={`ip-type-chip ip-type-${item.insight_type}`}>
                    {formatInsightIcon(item.insight_type)}
                    {typeOptions.find((o) => o.value === item.insight_type)?.label ?? item.insight_type}
                  </span>
                  <span className="ip-confidence" style={{ color: confidenceColor(item.confidence) }}>
                    {describeConfidence(item.confidence)}
                  </span>
                </div>
                <h3 className="ip-card-title">{item.title}</h3>
                <p className="ip-card-body">{item.content}</p>
                <div className="ip-card-footer">
                  {item.created_at
                    ? new Date(item.created_at).toLocaleDateString("zh-CN", {
                        year: "numeric",
                        month: "long",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })
                    : ""}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
