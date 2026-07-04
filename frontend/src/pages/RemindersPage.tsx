import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Bell,
  CalendarClock,
  CheckCircle2,
  Clock,
  Forward,
  Globe,
  MoreHorizontal,
  Trash2,
} from "lucide-react";
import { api } from "../api/client";
import type { ReminderItem } from "../api/types";
import { formatDateTimeLong } from "../utils/presentation";
import "../styles/reminders.css";

type TabKey = "upcoming" | "overdue" | "all";

const tabs: Array<{ key: TabKey; label: string; icon: typeof Clock }> = [
  { key: "upcoming", label: "即将到来", icon: Clock },
  { key: "overdue",  label: "已逾期",     icon: AlertCircle },
  { key: "all",      label: "全部",       icon: Bell },
];

function isOverdue(r: ReminderItem): boolean {
  if (!r.due_at) return r.type === "overdue";
  return new Date(r.due_at).getTime() < Date.now();
}

function compareOverdue(a: ReminderItem, b: ReminderItem) {
  if (!a.due_at && !b.due_at) return a.title.localeCompare(b.title);
  if (!a.due_at) return 1;
  if (!b.due_at) return -1;
  return new Date(b.due_at).getTime() - new Date(a.due_at).getTime();
}

function compareUpcoming(a: ReminderItem, b: ReminderItem) {
  if (!a.due_at && !b.due_at) return a.title.localeCompare(b.title);
  if (!a.due_at) return 1;
  if (!b.due_at) return -1;
  return new Date(a.due_at).getTime() - new Date(b.due_at).getTime();
}

function timeUntil(dueAt: string | null): string {
  if (!dueAt) return "";
  const diff = new Date(dueAt).getTime() - Date.now();
  const absDiff = Math.abs(diff);
  const mins = Math.round(absDiff / 60000);
  if (mins < 60) return diff > 0 ? `${mins}分钟后` : `${mins}分钟前`;
  const hours = Math.round(absDiff / 3600000);
  if (hours < 24) return diff > 0 ? `${hours}小时后` : `${hours}小时前`;
  const days = Math.round(absDiff / 86400000);
  return diff > 0 ? `${days}天后` : `${days}天前`;
}

// Pick an icon based on reminder type/title
function reminderIcon(item: ReminderItem, overdue: boolean) {
  if (overdue) return <AlertCircle size={20} />;
  const t = item.title.toLowerCase();
  if (t.includes("世界杯") || t.includes("world")) return <Globe size={20} />;
  if (t.includes("提醒") || t.includes("铃")) return <Bell size={20} />;
  if (item.due_at) return <Clock size={20} />;
  return <Bell size={20} />;
}

export function RemindersPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<TabKey>("upcoming");
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; item: ReminderItem } | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["dashboard-reminders", "center"],
    queryFn:  () => api.getDashboardReminders(50),
  });

  const reminders = data ?? [];

  const overdueItems  = useMemo(() => reminders.filter(isOverdue).sort(compareOverdue), [reminders]);
  const upcomingItems = useMemo(() => reminders.filter((r) => !isOverdue(r)).sort(compareUpcoming), [reminders]);

  const visible = useMemo(() => {
    if (tab === "overdue")  return overdueItems;
    if (tab === "upcoming") return upcomingItems;
    return [...reminders].sort(compareOverdue);
  }, [tab, overdueItems, upcomingItems, reminders]);

  const counts = { upcoming: upcomingItems.length, overdue: overdueItems.length, all: reminders.length };

  const invalidateReminders = () => {
    queryClient.invalidateQueries({ queryKey: ["dashboard-reminders"] });
    queryClient.refetchQueries({ queryKey: ["dashboard-reminders"] });
  };

  const snoozeMutation = useMutation({
    mutationFn: ({ id, dueAt }: { id: string; dueAt: string }) =>
      api.updateReminder(id, { due_at: dueAt }),
    onSuccess: () => { invalidateReminders(); setCtxMenu(null); },
    onError: (err) => { console.error("snoozeReminder failed:", err); setCtxMenu(null); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.updateReminder(id, { status: "dismissed" }),
    onSuccess: () => { invalidateReminders(); setCtxMenu(null); },
    onError: (err) => { console.error("dismissReminder failed:", err); setCtxMenu(null); },
  });

  function handleCardContext(e: React.MouseEvent, item: ReminderItem) {
    e.preventDefault();
    setCtxMenu({ x: e.clientX, y: e.clientY, item });
  }

  function snooze(hours: number) {
    if (!ctxMenu) return;
    const newDue = new Date(Date.now() + hours * 3600000).toISOString();
    snoozeMutation.mutate({ id: ctxMenu.item.id, dueAt: newDue });
  }

  function handleDismiss(id: string) {
    deleteMutation.mutate(id);
  }

  return (
    <div className="rm-page">
      <div className="rm-header">
        <Bell size={22} className="rm-header-icon" />
        <div>
          <h1 className="rm-title">{"提醒"}</h1>
          <p className="rm-subtitle">
            {"到点、临近、逾期、紧急或重要的待办，系统会自动提到这里。"}
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="rm-tabs">
        {tabs.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.key}
              type="button"
              className={`rm-tab${tab === t.key ? " active" : ""}`}
              onClick={() => setTab(t.key)}
            >
              <Icon size={15} />
              <span>{t.label}</span>
              <span className="rm-tab-count">{counts[t.key]}</span>
            </button>
          );
        })}
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="rm-loading">
          {[1, 2, 3].map((i) => <div key={i} className="rm-skeleton" />)}
        </div>
      ) : error ? (
        <div className="rm-error">{"提醒列表加载失败，请确认后端服务已启动。"}</div>
      ) : visible.length === 0 ? (
        <div className="rm-empty">
          <CheckCircle2 size={36} />
          <p>
            {tab === "overdue"
              ? "没有逾期的提醒，做得不错！"
              : tab === "upcoming"
                ? "暂时没有即将到来的提醒。"
                : "当前没有提醒。给待办设置截止时间，系统会自动归集。"}
          </p>
        </div>
      ) : (
        <div className="rm-list">
          {visible.map((item) => {
            const overdue = isOverdue(item);
            const rel = timeUntil(item.due_at);
            return (
              <article
                key={`${item.todo_id}-${item.type}`}
                className={`rm-card${overdue ? " rm-card-overdue" : ""}`}
                onContextMenu={(e) => handleCardContext(e, item)}
              >
                {/* Left: icon + type badge */}
                <div className="rm-card-left">
                  <div className={`rm-card-icon-wrap${overdue ? " overdue" : ""}`}>
                    {reminderIcon(item, overdue)}
                  </div>
                  <span className={`rm-card-badge${overdue ? " overdue" : ""}`}>
                    {overdue ? "已逾期" : item.type === "due_soon" ? "即将到点" : "提醒"}
                  </span>
                </div>

                {/* Center: content */}
                <div className="rm-card-body">
                  <h3 className="rm-card-title">{item.title}</h3>
                  {item.message && (
                    <p className="rm-card-message">{item.message}</p>
                  )}
                  {item.due_at && (
                    <span className="rm-card-date">
                      <CalendarClock size={13} />
                      {formatDateTimeLong(item.due_at)}
                    </span>
                  )}
                </div>

                {/* Right: time + action */}
                <div className="rm-card-right">
                  {rel && <span className="rm-card-rel">{rel}</span>}
                  <button
                    className={`rm-card-action${overdue ? " urgent" : ""}`}
                    type="button"
                    onClick={() => handleDismiss(item.id)}
                  >
                    {"处理提醒"}
                  </button>
                  <button
                    className="rm-card-more"
                    type="button"
                    onClick={(e) => handleCardContext(e, item)}
                  >
                    <MoreHorizontal size={16} />
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}

      {/* Footer */}
      {visible.length > 0 && (
        <div className="rm-footer">
          <svg viewBox="0 0 48 48" fill="none" width="36" height="36">
            <path d="M24 6 C30 6 35 12 35 20 C35 26 30 30 28 34 H20 C18 30 13 26 13 20 C13 12 18 6 24 6Z" fill="#8cb89c" opacity="0.3"/>
            <path d="M20 36h8M21 39h6" stroke="#6b9e7a" strokeWidth="1.5" strokeLinecap="round" opacity="0.4"/>
            <path d="M16 14 C14 10 18 6 22 8" stroke="#6b9e7a" strokeWidth="1" opacity="0.3"/>
            <path d="M32 14 C34 10 30 6 26 8" stroke="#6b9e7a" strokeWidth="1" opacity="0.3"/>
            <circle cx="14" cy="8" r="2" fill="#a8d5b8" opacity="0.25"/>
            <circle cx="34" cy="8" r="2" fill="#a8d5b8" opacity="0.25"/>
          </svg>
          <span>{"及时处理逾期提醒，让重要的事情不再被遗漏 ~"}</span>
        </div>
      )}

      {ctxMenu && (() => {
        const item = ctxMenu.item;
        return (
          <>
            <div className="rm-ctx-overlay" onClick={() => setCtxMenu(null)} onContextMenu={(e) => { e.preventDefault(); setCtxMenu(null); }} />
            <div className="rm-ctx-menu" style={{ left: ctxMenu.x, top: ctxMenu.y }}>
              <button className="rm-ctx-item" onClick={() => snooze(1)}>
                <Forward size={14} />
                <span>{"推迟 1 小时"}</span>
              </button>
              <button className="rm-ctx-item" onClick={() => snooze(24)}>
                <Clock size={14} />
                <span>{"推迟到明天"}</span>
              </button>
              <button className="rm-ctx-item" onClick={() => snooze(168)}>
                <CalendarClock size={14} />
                <span>{"推迟到下周"}</span>
              </button>
              <div className="rm-ctx-divider" />
              <button className="rm-ctx-item danger" onClick={() => deleteMutation.mutate(item.id)}>
                <Trash2 size={14} />
                <span>{"删除提醒"}</span>
              </button>
            </div>
          </>
        );
      })()}
    </div>
  );
}
