import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { formatDateLabel, formatDateTimeLong, formatFactType, formatTimelineType } from "../utils/presentation";

const signalFilters = [
  { label: "全部信号", value: "all" },
  { label: "消费", value: "expense" },
  { label: "状态", value: "mood" },
  { label: "学习", value: "learning" },
  { label: "计划", value: "plan" },
];

export function TimelinePage() {
  const [view, setView] = useState<"events" | "signals">("signals");
  const [signalFilter, setSignalFilter] = useState("all");

  const {
    data: events,
    isLoading: eventsLoading,
    error: eventsError,
  } = useQuery({
    queryKey: ["timeline"],
    queryFn: api.listTimeline,
  });

  const {
    data: signals,
    isLoading: signalsLoading,
    error: signalsError,
  } = useQuery({
    queryKey: ["timeline-signals", signalFilter],
    queryFn: () => api.listMemorySignals(signalFilter === "all" ? undefined : signalFilter),
  });

  const visibleSignals = signals ?? [];
  const visibleEvents = events ?? [];
  const isLoading = view === "signals" ? signalsLoading : eventsLoading;
  const hasError = view === "signals" ? signalsError : eventsError;

  const signalSummary = useMemo(() => {
    const total = visibleSignals.length;
    const topType = visibleSignals.reduce<Record<string, number>>((acc, signal) => {
      acc[signal.fact_type] = (acc[signal.fact_type] ?? 0) + 1;
      return acc;
    }, {});
    const [type, count] = Object.entries(topType).sort((a, b) => b[1] - a[1])[0] ?? [];
    if (!type) {
      return "还没有形成稳定记忆信号。继续随手记录，系统会逐步识别消费、状态、学习和计划。";
    }
    return `当前筛选下共有 ${total} 条信号，最多的是${formatFactType(type)}，共 ${count} 条。`;
  }, [visibleSignals]);

  if (isLoading) {
    return <div className="loading">正在加载时间线...</div>;
  }

  if (hasError) {
    return <div className="error">时间线加载失败。</div>;
  }

  return (
    <div className="page-grid">
      <section className="panel warm-panel timeline-hero">
        <div>
          <span className="eyebrow">Temporal Memory</span>
          <h3>最近这段时间</h3>
          <p className="panel-subtitle">系统动态记录操作轨迹，记忆信号展示 AI 从非结构化输入里理解出的长期事实。</p>
        </div>
        <div className="timeline-summary">
          <strong>{view === "signals" ? visibleSignals.length : visibleEvents.length}</strong>
          <span>{view === "signals" ? "条记忆信号" : "条系统动态"}</span>
        </div>
      </section>

      <section className="panel">
        <div className="section-title">
          <div>
            <h3>{view === "signals" ? "记忆信号流" : "系统动态"}</h3>
            <p className="panel-subtitle">{view === "signals" ? signalSummary : "把记录、待办和提醒放在同一条时间线上，更容易回想最近发生了什么。"}</p>
          </div>
          <div className="segmented-control" aria-label="时间线视图">
            <button className={view === "signals" ? "active" : ""} type="button" onClick={() => setView("signals")}>
              记忆信号
            </button>
            <button className={view === "events" ? "active" : ""} type="button" onClick={() => setView("events")}>
              系统动态
            </button>
          </div>
        </div>

        {view === "signals" ? (
          <>
            <div className="signal-filter-row" role="tablist" aria-label="信号类型筛选">
              {signalFilters.map((filter) => (
                <button
                  className={`signal-filter-chip${signalFilter === filter.value ? " active" : ""}`}
                  key={filter.value}
                  type="button"
                  onClick={() => setSignalFilter(filter.value)}
                >
                  {filter.label}
                </button>
              ))}
            </div>
            <div className="timeline-list signal-timeline-list">
              {visibleSignals.length === 0 ? (
                <div className="empty-state">这里还没有匹配的记忆信号。先记下一些生活、消费、计划或学习内容，它会慢慢长出来。</div>
              ) : (
                visibleSignals.map((item) => (
                  <Link className={`timeline-item signal-item signal-item-${item.tone}`} key={item.id} to={`/app/memories/${item.memory_id}`}>
                    <div className="timeline-header">
                      <span className="soft-tag">{formatFactType(item.fact_type)}</span>
                      <span className="muted">{formatDateLabel(item.event_time)}</span>
                    </div>
                    <strong>{item.title}</strong>
                    <p className="panel-subtitle">{item.summary}</p>
                    <div className="inline-meta">
                      <span>{formatDateTimeLong(item.event_time)}</span>
                      <span>{Math.round(item.confidence_score * 100)}% 可信度</span>
                    </div>
                  </Link>
                ))
              )}
            </div>
          </>
        ) : (
          <div className="timeline-list">
            {visibleEvents.length === 0 ? (
              <div className="empty-state">这里还没有内容。你记下第一条记录后，时间线就会开始生长。</div>
            ) : (
              visibleEvents.map((item) => (
                <div className="timeline-item" key={item.id}>
                  <div className="timeline-header">
                    <span className="soft-tag">{formatTimelineType(item.event_type)}</span>
                    <span className="muted">{formatDateLabel(item.event_time)}</span>
                  </div>
                  <strong>{item.title}</strong>
                  <p className="panel-subtitle">{item.summary}</p>
                  <div className="inline-meta">
                    <span>{formatDateTimeLong(item.event_time)}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </section>
    </div>
  );
}
