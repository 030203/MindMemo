import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BellRing, CalendarClock, CheckSquare, Clock3, ListFilter } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ReminderItem } from "../api/types";
import { formatDateTimeLong } from "../utils/presentation";

type ReminderFilter = "all" | "high" | "medium" | "low";

const filterOptions: Array<{ key: ReminderFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "high", label: "高优先" },
  { key: "medium", label: "近期" },
  { key: "low", label: "稍后" },
];

function formatReminderType(type: string) {
  const map: Record<string, string> = {
    overdue: "已过期",
    due_soon: "即将到点",
    urgent: "紧急",
    important: "重要",
    blocked: "卡住了",
  };
  return map[type] ?? type;
}

function formatReminderLevel(level: string) {
  if (level === "high") return "需要现在看到";
  if (level === "medium") return "今天留意";
  return "有空再看";
}

function compareReminderTime(a: ReminderItem, b: ReminderItem) {
  if (!a.due_at && !b.due_at) return a.title.localeCompare(b.title);
  if (!a.due_at) return 1;
  if (!b.due_at) return -1;
  return new Date(a.due_at).getTime() - new Date(b.due_at).getTime();
}

export function RemindersPage() {
  const [filter, setFilter] = useState<ReminderFilter>("all");
  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard-reminders", "center"],
    queryFn: () => api.getDashboardReminders(50),
  });

  const reminders = data ?? [];
  const visibleReminders = useMemo(
    () =>
      reminders
        .filter((item) => filter === "all" || item.level === filter)
        .sort(compareReminderTime),
    [filter, reminders],
  );

  const dueSoonCount = reminders.filter((item) => item.type === "due_soon" || item.type === "overdue").length;
  const highCount = reminders.filter((item) => item.level === "high").length;
  const timedCount = reminders.filter((item) => item.due_at).length;

  if (isLoading) {
    return <div className="loading">正在整理需要提醒你的事情...</div>;
  }

  if (error) {
    return <div className="error">提醒列表加载失败，请确认后端服务已经启动。</div>;
  }

  return (
    <div className="page-grid reminders-page">
      <section className="reminder-overview">
        <div className="reminder-overview-main">
          <span className="eyebrow">Reminder Center</span>
          <h3>真正需要提醒你的事件</h3>
          <p>这里不是所有待办，而是系统判断应该主动浮出来的事项：到点、临近、逾期、紧急、重要或卡住的任务。</p>
        </div>
        <div className="reminder-stat-strip">
          <div>
            <BellRing size={18} />
            <strong>{reminders.length}</strong>
            <span>当前提醒</span>
          </div>
          <div>
            <Clock3 size={18} />
            <strong>{dueSoonCount}</strong>
            <span>临近/逾期</span>
          </div>
          <div>
            <CalendarClock size={18} />
            <strong>{timedCount}</strong>
            <span>有明确时间</span>
          </div>
          <div>
            <ListFilter size={18} />
            <strong>{highCount}</strong>
            <span>高优先</span>
          </div>
        </div>
      </section>

      <section className="panel reminder-toolbar">
        <div>
          <h3>提醒筛选</h3>
          <p className="panel-subtitle">待办可以很多，但提醒只放需要主动打断你的事情。</p>
        </div>
        <div className="segmented-control" aria-label="提醒筛选">
          {filterOptions.map((option) => (
            <button
              className={filter === option.key ? "active" : ""}
              key={option.key}
              type="button"
              onClick={() => setFilter(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </section>

      <section className="reminder-list-panel">
        {visibleReminders.length === 0 ? (
          <div className="empty-state reminder-empty">
            当前没有符合条件的提醒。给待办设置截止时间，或在随手记里写“提醒我”，系统会把该出现的事件放到这里。
          </div>
        ) : (
          <div className="reminder-page-list">
            {visibleReminders.map((item) => (
              <article className={`reminder-event-card reminder-event-${item.level}`} key={`${item.todo_id}-${item.type}`}>
                <div className="reminder-event-icon">
                  <BellRing size={18} />
                </div>
                <div className="reminder-event-body">
                  <div className="reminder-event-topline">
                    <span>{formatReminderType(item.type)}</span>
                    <span>{formatReminderLevel(item.level)}</span>
                  </div>
                  <h3>{item.title}</h3>
                  <p>{item.message}</p>
                  <div className="reminder-event-meta">
                    <span>
                      <CalendarClock size={15} />
                      {formatDateTimeLong(item.due_at)}
                    </span>
                    <Link to="/todos">
                      <CheckSquare size={15} />
                      查看关联待办
                    </Link>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
