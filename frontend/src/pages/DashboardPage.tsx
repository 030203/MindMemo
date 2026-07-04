import { useMemo, useRef, useState, useEffect, useCallback } from "react";
import type { ChangeEvent, KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  CalendarClock,
  CheckSquare,
  ChevronRight,
  Clock,
  ImagePlus,
  Loader2,
  MessageSquare,
  Paperclip,
  PenLine,
  Plus,
  Search,
  Send,
  Settings,
  Sparkles,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import MarkdownRenderer from "../components/MarkdownRenderer";
import type { ChatSessionResponse, ReminderItem, TodoItem } from "../api/types";
import "../styles/dashboard.css";

// ── helpers ──────────────────────────────────────────────────────────────────

function formatRelativeDate(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfTomorrow = new Date(startOfToday.getTime() + 86400000);
  const startOfDayAfter = new Date(startOfTomorrow.getTime() + 86400000);
  if (d >= startOfToday && d < startOfTomorrow) return "今天";
  if (d >= startOfTomorrow && d < startOfDayAfter) return "明天";
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`;
}

function todayDateLabel(): string {
  const d = new Date();
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(d);
}

function sortByDue(a: TodoItem, b: TodoItem) {
  const ta = a.due_at ? new Date(a.due_at).getTime() : Number.MAX_SAFE_INTEGER;
  const tb = b.due_at ? new Date(b.due_at).getTime() : Number.MAX_SAFE_INTEGER;
  return ta - tb;
}

function reminderDotClass(level: string) {
  if (level === "high") return "dashboard-reminder-dot";
  if (level === "medium") return "dashboard-reminder-dot dot-blue";
  return "dashboard-reminder-dot dot-green";
}

function reminderTimeLabel(item: ReminderItem) {
  if (!item.due_at) return "";
  const d = new Date(item.due_at);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const diffDays = Math.round((d.getTime() - now.getTime()) / 86400000);
  if (diffDays < 0) return "已过期";
  if (diffDays === 0) {
    return `今天 ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
  }
  const weekdays = ["日", "一", "二", "三", "四", "五", "六"];
  return `每${weekdays[d.getDay()]} ${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

/** 会话的第一条用户消息预览 */
function sessionPreview(title: string | null, contextType: string) {
  if (title) return title;
  if (contextType === "global") return "全局对话";
  return "新对话";
}

/** 格式化相对时间（今天/昨天/7月25日） */
function formatSessionTime(dateStr: string): string {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterdayStart = new Date(todayStart.getTime() - 86400000);
  if (d >= todayStart) return "刚刚";
  if (d >= yesterdayStart) return "昨天";
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

// ── Time preset helpers ──────────────────────────────────────────────────────

function toDatetimeLocal(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const TODO_PRESETS: Array<{ label: string; build: () => string }> = [
  { label: "今天", build: () => { const d = new Date(); d.setHours(18, 0, 0, 0); return toDatetimeLocal(d); } },
  { label: "明天", build: () => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); return toDatetimeLocal(d); } },
  { label: "后天", build: () => { const d = new Date(); d.setDate(d.getDate() + 2); d.setHours(9, 0, 0, 0); return toDatetimeLocal(d); } },
  { label: "下周一", build: () => { const d = new Date(); const diff = (8 - d.getDay()) % 7 || 7; d.setDate(d.getDate() + diff); d.setHours(9, 0, 0, 0); return toDatetimeLocal(d); } },
];

const REMINDER_PRESETS: Array<{ label: string; build: () => string }> = [
  { label: "1 小时后", build: () => { const d = new Date(); d.setHours(d.getHours() + 1); return toDatetimeLocal(d); } },
  { label: "今晚 9 点", build: () => { const d = new Date(); d.setHours(21, 0, 0, 0); return toDatetimeLocal(d); } },
  { label: "明早 8 点", build: () => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(8, 0, 0, 0); return toDatetimeLocal(d); } },
  { label: "明天 9 点", build: () => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); return toDatetimeLocal(d); } },
];

// ── Component ─────────────────────────────────────────────────────────────────

export function DashboardPage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const aiInputRef = useRef<HTMLInputElement | null>(null);
  const aiMessageEndRef = useRef<HTMLDivElement | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<{ id: string; file: File }[]>([]);
  const [toast, setToast] = useState("");
  const [captureMode, setCaptureMode] = useState<"memo" | "todo" | "reminder">("memo");
  const [dueAt, setDueAt] = useState("");
  const [remindAt, setRemindAt] = useState("");

  // AI panel state
  const [aiOpen, setAiOpen] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [chatMessages, setChatMessages] = useState<{ role: string; content: string }[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [sessionSearch, setSessionSearch] = useState("");

  // ── queries ────────────────────────────────────────────────────────────────
  const { data: memories } = useQuery({
    queryKey: ["memories", "dashboard"],
    queryFn: () => api.listMemories(),
  });
  const { data: todos } = useQuery({
    queryKey: ["todos", "dashboard"],
    queryFn: () => api.listTodos({ sort: "due" }),
  });
  const { data: overview } = useQuery({
    queryKey: ["dashboard-overview"],
    queryFn: api.getDashboardOverview,
  });
  const { data: reminders } = useQuery({
    queryKey: ["dashboard-reminders", "home"],
    queryFn: () => api.getDashboardReminders(4),
  });
  const { data: sessions, refetch: refetchSessions } = useQuery({
    queryKey: ["chat-sessions"],
    queryFn: () => api.listSessions(),
    enabled: aiOpen,
  });

  // ── derived ────────────────────────────────────────────────────────────────
  const recentMemories = useMemo(() => (memories ?? []).slice(0, 3), [memories]);
  const pendingTodos = useMemo(
    () => (todos ?? []).filter((t) => t.status !== "done").sort(sortByDue).slice(0, 4),
    [todos],
  );
  const upcomingReminders = useMemo(() => (reminders ?? []).slice(0, 4), [reminders]);
  const pendingCount = (todos ?? []).filter((t) => t.status !== "done").length;
  const actionableCount = overview?.today_todos ?? 0;

  const filteredSessions = useMemo(() => {
    if (!sessions) return [];
    if (!sessionSearch.trim()) return sessions;
    const q = sessionSearch.toLowerCase();
    return sessions.filter((s) =>
      (s.title ?? "").toLowerCase().includes(q)
    );
  }, [sessions, sessionSearch]);

  // ── mutations ──────────────────────────────────────────────────────────────
  const captureMutation = useMutation({
    mutationFn: () => {
      if (attachments.length > 0) {
        // Multipart: text + file attachments
        const form = new FormData();
        form.append("content", draft.trim());
        form.append("record_type", captureMode);
        if (captureMode === "todo" && dueAt) {
          form.append("due_at", new Date(dueAt).toISOString());
        }
        if (captureMode === "reminder" && remindAt) {
          form.append("remind_at", new Date(remindAt).toISOString());
        }
        for (const att of attachments) {
          form.append("files", att.file, att.file.name);
        }
        return api.ingestCapture(form);
      }
      // JSON: text only
      return api.ingestText({
        content: draft.trim(),
        record_type: captureMode,
        due_at: captureMode === "todo" && dueAt ? new Date(dueAt).toISOString() : null,
        remind_at: captureMode === "reminder" && remindAt ? new Date(remindAt).toISOString() : null,
      });
    },
    onSuccess: () => {
      setDraft("");
      setAttachments([]);
      setDueAt("");
      setRemindAt("");
      setCaptureMode("memo");
      const tips: Record<string, string> = {
        memo: "已保存",
        todo: "已加入待办",
        reminder: "已设置提醒",
      };
      setToast(tips[captureMode] ?? "已保存");
      queryClient.invalidateQueries({ queryKey: ["memories"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
      queryClient.invalidateQueries({ queryKey: ["todos"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-reminders"] });
    },
    onError: () => setToast("保存失败，请重试"),
  });

  // ── AI helpers ─────────────────────────────────────────────────────────────
  function cancelStream() {
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    setChatLoading(false);
  }

  async function ensureSession(): Promise<string> {
    const s = await api.createOrGetSession({ context_type: "global", context_id: null, title: null });
    setSessionId(s.session_id);
    return s.session_id;
  }

  async function loadMessages(sid: string) {
    try {
      const msgs = await api.getSessionMessages(sid);
      setChatMessages(msgs.map((m) => ({ role: m.role, content: m.content })));
    } catch {
      setChatMessages([]);
    }
  }

  const openAi = useCallback(async () => {
    cancelStream();
    setQuestion("");
    setAiOpen(true);
    const sid = await ensureSession();
    await loadMessages(sid);
    refetchSessions();
  }, []);

  /** 新建对话：强制创建一个新的 session（用随机标题保证不复用） */
  async function createNewSession() {
    cancelStream();
    setChatMessages([]);
    setQuestion("");
    const s = await api.createOrGetSession({
      context_type: "global",
      context_id: crypto.randomUUID(),
      title: null,
    });
    setSessionId(s.session_id);
    await loadMessages(s.session_id);
    refetchSessions();
  }

  /** 切换到已有会话 */
  async function switchSession(s: ChatSessionResponse) {
    if (s.session_id === sessionId) return;
    cancelStream();
    setChatMessages([]);
    setSessionId(s.session_id);
    await loadMessages(s.session_id);
  }

  useEffect(() => {
    const handler = () => { openAi(); };
    window.addEventListener("open-ai-drawer", handler);
    return () => { window.removeEventListener("open-ai-drawer", handler); cancelStream(); };
  }, [openAi]);

  useEffect(() => {
    if (!aiOpen) return;
    const frame = requestAnimationFrame(() => {
      aiInputRef.current?.focus();
      aiMessageEndRef.current?.scrollIntoView({ behavior: "smooth" });
    });
    return () => cancelAnimationFrame(frame);
  }, [aiOpen, chatMessages]);

  async function submitQuestion(q = question) {
    const trimmed = q.trim();
    if (!trimmed || chatLoading) return;

    let sid = sessionId;
    if (!sid) {
      sid = await ensureSession();
    }

    setQuestion("");
    const assistIdx = chatMessages.length + 1;
    setChatMessages((prev) => [
      ...prev,
      { role: "user", content: trimmed },
      { role: "assistant", content: "" },
    ]);
    setChatLoading(true);
    let full = "";
    const ctrl = new AbortController();
    streamAbortRef.current = ctrl;
    api.askInSessionStream(
      sid,
      { question: trimmed },
      (chunk) => {
        full += chunk;
        setChatMessages((prev) =>
          prev.map((m, i) => (i === assistIdx ? { ...m, content: full } : m))
        );
      },
      () => {
        setChatLoading(false);
        streamAbortRef.current = null;
        refetchSessions();
      },
      () => {
        setChatLoading(false);
        streamAbortRef.current = null;
      },
      ctrl.signal,
    );
  }

  function handleCaptureKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const canSubmit =
        draft.trim() &&
        !captureMutation.isPending &&
        (captureMode !== "reminder" || remindAt.length > 0);
      if (canSubmit) captureMutation.mutate();
    }
  }

  function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []).map((f) => ({ id: crypto.randomUUID(), file: f }));
    setAttachments((p) => [...p, ...files]);
    e.target.value = "";
  }

  // ── render ─────────────────────────────────────────────────────────────────
  return (
    <div className={`dashboard-root${aiOpen ? " ai-panel-open" : ""}`}>
      {/* Click-away overlay: closes the AI panel when clicking the main area */}
      {aiOpen && (
        <div
          className="ai-panel-overlay"
          onClick={() => { cancelStream(); setAiOpen(false); }}
          aria-hidden="true"
        />
      )}
      {/* ── Main content ───────────────────────────────────────────────────── */}
      <div className="dashboard-page">
        {/* Header */}
        <div className="dashboard-header">
          <div className="dashboard-header-left">
            <h1>
              今天，继续记录吧
              <span className="sparkle-icon">🌱</span>
            </h1>
            <div className="dashboard-header-date">{todayDateLabel()}</div>
          </div>
          <div className="dashboard-header-actions">
            <button
              className={`dashboard-ai-btn${aiOpen ? " active" : ""}`}
              type="button"
              onClick={aiOpen ? () => { cancelStream(); setAiOpen(false); } : openAi}
            >
              <MessageSquare size={15} />
              AI 对话
            </button>
            <Link className="dashboard-settings-icon" to="/app/settings" aria-label="设置">
              <Settings size={17} />
            </Link>
          </div>
        </div>

        {/* Summary card with nature theme */}
        <div className="dashboard-summary-card">
          <svg className="dashboard-summary-plant dashboard-summary-plant-left" viewBox="0 0 120 160" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M60 160 C60 100 30 80 20 40 C15 20 30 5 45 15 C55 22 58 35 60 50" stroke="#8cb89c" strokeWidth="2" fill="none" opacity="0.5"/>
            <path d="M60 140 C50 120 25 110 18 80 C12 55 28 35 42 48 C52 58 57 80 60 100" stroke="#a8d5b8" strokeWidth="1.5" fill="none" opacity="0.4"/>
            <ellipse cx="22" cy="38" rx="14" ry="22" fill="#8cb89c" opacity="0.15" transform="rotate(-15 22 38)"/>
            <ellipse cx="18" cy="78" rx="12" ry="18" fill="#a8d5b8" opacity="0.12" transform="rotate(-20 18 78)"/>
            <ellipse cx="40" cy="20" rx="10" ry="16" fill="#6b9e7a" opacity="0.12" transform="rotate(10 40 20)"/>
            <circle cx="45" cy="12" r="3" fill="#8cb89c" opacity="0.25"/>
            <circle cx="15" cy="55" r="2.5" fill="#a8d5b8" opacity="0.2"/>
          </svg>
          <svg className="dashboard-summary-plant dashboard-summary-plant-right" viewBox="0 0 120 160" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M60 160 C60 110 80 85 90 50 C95 30 82 10 68 18 C60 25 58 40 60 55" stroke="#8cb89c" strokeWidth="2" fill="none" opacity="0.5"/>
            <path d="M60 135 C65 115 85 100 92 72 C98 48 80 30 66 42 C58 50 58 75 60 95" stroke="#a8d5b8" strokeWidth="1.5" fill="none" opacity="0.4"/>
            <ellipse cx="92" cy="48" rx="14" ry="20" fill="#8cb89c" opacity="0.15" transform="rotate(15 92 48)"/>
            <ellipse cx="95" cy="80" rx="11" ry="16" fill="#a8d5b8" opacity="0.12" transform="rotate(20 95 80)"/>
            <ellipse cx="72" cy="22" rx="10" ry="14" fill="#6b9e7a" opacity="0.12" transform="rotate(-10 72 22)"/>
            <circle cx="75" cy="15" r="3" fill="#8cb89c" opacity="0.25"/>
          </svg>
          <div className="dashboard-summary-text">
            <p>你今天已经记录了 <strong>{overview?.recent_memories ?? 0}</strong> 条想法，其中 <strong>{actionableCount}</strong> 条需要行动，AI 已为你整理完成。</p>
          </div>
          <div className="dashboard-summary-stats">
            <div className="dashboard-stat-pill">
              <Sparkles size={14} className="stat-icon-idea" />
              <strong>{overview?.recent_memories ?? 0}</strong>
              <span>想法</span>
            </div>
            <div className="dashboard-stat-pill">
              <CheckSquare size={14} className="stat-icon-todo" />
              <strong>{actionableCount}</strong>
              <span>待办</span>
            </div>
            <div className="dashboard-stat-pill">
              <Bell size={14} className="stat-icon-remind" />
              <strong>{upcomingReminders.length}</strong>
              <span>提醒</span>
            </div>
          </div>
        </div>

        {/* Quick capture */}
        <div className="dashboard-capture-card">
          <textarea
            className="dashboard-capture-input"
            placeholder={
              captureMode === "todo"
                ? "输入待办事项..."
                : captureMode === "reminder"
                  ? "输入提醒内容..."
                  : "输入任何东西..."
            }
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleCaptureKey}
            rows={2}
          />
          {!draft && (
            <div className="dashboard-capture-placeholder-sub">
              {captureMode === "todo"
                ? "需要处理的事情..."
                : captureMode === "reminder"
                  ? "到点提醒你的事情..."
                  : "想法、待办、灵感、问题..."}
            </div>
          )}

          {/* Mode switch chips */}
          <div className="dashboard-capture-modes">
            <button
              className={`dashboard-capture-mode-chip${captureMode === "memo" ? " active" : ""}`}
              type="button"
              onClick={() => setCaptureMode("memo")}
            >
              <PenLine size={14} />
              记录
            </button>
            <button
              className={`dashboard-capture-mode-chip${captureMode === "todo" ? " active" : ""}`}
              type="button"
              onClick={() => setCaptureMode("todo")}
            >
              <CheckSquare size={14} />
              待办
            </button>
            <button
              className={`dashboard-capture-mode-chip${captureMode === "reminder" ? " active" : ""}`}
              type="button"
              onClick={() => setCaptureMode("reminder")}
            >
              <Bell size={14} />
              提醒
            </button>
          </div>

          {/* Date/time pickers for todo & reminder modes */}
          {captureMode === "todo" && (
            <div className="dashboard-capture-datetime-panel">
              <div className="dashboard-capture-datetime-header">
                <CalendarClock size={15} />
                <span>截止日期</span>
                <span className="dashboard-capture-optional-tag">可选</span>
                {dueAt && (
                  <button
                    type="button"
                    className="dashboard-capture-datetime-clear"
                    onClick={() => setDueAt("")}
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
              <input
                type="datetime-local"
                className="dashboard-capture-datetime-input"
                value={dueAt}
                onChange={(e) => setDueAt(e.target.value)}
              />
              <div className="dashboard-capture-datetime-presets">
                {TODO_PRESETS.map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    className={`dashboard-capture-preset-chip${dueAt === p.build() ? " active" : ""}`}
                    onClick={() => setDueAt(p.build())}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          )}
          {captureMode === "reminder" && (
            <div className="dashboard-capture-datetime-panel">
              <div className="dashboard-capture-datetime-header">
                <Clock size={15} />
                <span>提醒时间</span>
                {remindAt && (
                  <button
                    type="button"
                    className="dashboard-capture-datetime-clear"
                    onClick={() => setRemindAt("")}
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
              <input
                type="datetime-local"
                className="dashboard-capture-datetime-input"
                value={remindAt}
                onChange={(e) => setRemindAt(e.target.value)}
              />
              <div className="dashboard-capture-datetime-presets">
                {REMINDER_PRESETS.map((p) => (
                  <button
                    key={p.label}
                    type="button"
                    className={`dashboard-capture-preset-chip${remindAt === p.build() ? " active" : ""}`}
                    onClick={() => setRemindAt(p.build())}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {attachments.length > 0 && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 8 }}>
              {attachments.map((a) => (
                <span
                  key={a.id}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 5,
                    padding: "3px 8px",
                    borderRadius: 6,
                    background: "#f0efec",
                    fontSize: "0.8rem",
                    color: "#555",
                  }}
                >
                  <Paperclip size={12} />
                  {a.file.name}
                  <button
                    type="button"
                    onClick={() => setAttachments((p) => p.filter((x) => x.id !== a.id))}
                    style={{ background: "none", border: "none", cursor: "pointer", padding: 0, color: "#aaa" }}
                  >
                    <X size={11} />
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="dashboard-capture-toolbar">
            <div className="dashboard-capture-tools">
              <button className="dashboard-capture-tool-btn" type="button" onClick={() => fileInputRef.current?.click()} aria-label="添加附件">
                <Plus size={16} />
              </button>
              <button className="dashboard-capture-tool-btn" type="button" onClick={() => fileInputRef.current?.click()} aria-label="添加图片">
                <ImagePlus size={16} />
              </button>
              <button className="dashboard-capture-tool-btn" type="button" onClick={() => fileInputRef.current?.click()} aria-label="上传文件">
                <Paperclip size={16} />
              </button>
              <input ref={fileInputRef} type="file" multiple hidden onChange={handleFileChange} />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              {toast && <span style={{ fontSize: "0.82rem", color: "#aaa" }}>{toast}</span>}
              <button
                className="dashboard-capture-submit"
                type="button"
                disabled={
                  !draft.trim() ||
                  captureMutation.isPending ||
                  (captureMode === "reminder" && !remindAt)
                }
                onClick={() => captureMutation.mutate()}
              >
                {captureMutation.isPending ? <Loader2 size={14} className="spin" /> : <PenLine size={14} />}
                {captureMode === "todo" ? "加入待办" : captureMode === "reminder" ? "设置提醒" : "记录"}
              </button>
            </div>
          </div>
        </div>

        {/* Three-column widgets */}
        <div className="dashboard-widgets">
          {/* Recent memories */}
          <div className="dashboard-widget">
            <div className="dashboard-widget-header">
              <h3>最近记录</h3>
              <Link className="dashboard-widget-link" to="/app/memories">
                查看全部
              </Link>
            </div>
            {recentMemories.length === 0 ? (
              <div className="dashboard-empty-mini">还没有记录，先写一条吧</div>
            ) : (
              recentMemories.map((m) => (
                <Link
                  key={m.id}
                  to={`/app/memories/${m.id}`}
                  style={{ textDecoration: "none", color: "inherit" }}
                >
                  <div className="dashboard-memory-item">
                    <strong>{m.title || "未命名记录"}</strong>
                    <span className="dashboard-memory-item-meta">
                      {m.event_time ? formatRelativeDate(m.event_time) : "刚才"}
                    </span>
                  </div>
                </Link>
              ))
            )}
          </div>

          {/* Todos */}
          <div className="dashboard-widget">
            <div className="dashboard-widget-header">
              <h3>待办</h3>
              <Link className="dashboard-widget-link" to="/app/todos">
                查看全部
              </Link>
            </div>
            {pendingTodos.length === 0 ? (
              <div className="dashboard-empty-mini">暂无待办事项</div>
            ) : (
              pendingTodos.map((todo) => {
                const rel = formatRelativeDate(todo.due_at);
                const isToday = rel === "今天";
                const isTomorrow = rel === "明天";
                return (
                  <div className="dashboard-todo-item" key={todo.id}>
                    <span className="dashboard-todo-checkbox" />
                    <div className="dashboard-todo-item-body">
                      <span>{todo.title}</span>
                    </div>
                    <span
                      className={`dashboard-todo-item-due ${
                        isToday ? "dashboard-todo-due-today" : isTomorrow ? "dashboard-todo-due-tomorrow" : ""
                      }`}
                    >
                      {rel}
                    </span>
                  </div>
                );
              })
            )}
            <Link to="/app/todos" style={{ textDecoration: "none" }}>
              <button className="dashboard-add-btn" type="button">
                <Plus size={14} />
                新增待办
              </button>
            </Link>
          </div>

          {/* Reminders */}
          <div className="dashboard-widget">
            <div className="dashboard-widget-header">
              <h3>提醒</h3>
              <Link className="dashboard-widget-link" to="/app/reminders">
                查看全部
              </Link>
            </div>
            {upcomingReminders.length === 0 ? (
              <div className="dashboard-empty-mini">暂无提醒</div>
            ) : (
              upcomingReminders.map((r, i) => (
                <div className="dashboard-reminder-item" key={`${r.todo_id}-${i}`}>
                  <span className={reminderDotClass(r.level)} />
                  <div className="dashboard-reminder-item-body">
                    <span>{r.title}</span>
                    <div className="dashboard-reminder-item-meta">{reminderTimeLabel(r)}</div>
                  </div>
                </div>
              ))
            )}
            <Link to="/app/reminders" style={{ textDecoration: "none" }}>
              <button className="dashboard-add-btn" type="button">
                <Plus size={14} />
                新增提醒
              </button>
            </Link>
          </div>
        </div>

        {/* AI Insight banner with mountain illustration */}
        <div className="dashboard-ai-insight">
          <svg className="dashboard-insight-bg" viewBox="0 0 800 200" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#e8f0e4" stopOpacity="0.6"/>
                <stop offset="100%" stopColor="#f5f0e5" stopOpacity="0.3"/>
              </linearGradient>
              <linearGradient id="mtn1" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#8cb89c" stopOpacity="0.3"/>
                <stop offset="100%" stopColor="#a8d5b8" stopOpacity="0.1"/>
              </linearGradient>
              <linearGradient id="mtn2" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#6b9e7a" stopOpacity="0.2"/>
                <stop offset="100%" stopColor="#8cb89c" stopOpacity="0.08"/>
              </linearGradient>
            </defs>
            <rect width="800" height="200" fill="url(#sky)"/>
            <path d="M0 200 L100 100 L200 140 L320 60 L440 120 L520 80 L600 130 L700 70 L800 110 L800 200 Z" fill="url(#mtn1)"/>
            <path d="M0 200 L80 140 L180 160 L280 110 L380 150 L500 100 L620 145 L740 95 L800 130 L800 200 Z" fill="url(#mtn2)"/>
            <path d="M580 170 C580 150 590 130 600 120 C610 110 620 115 618 125 C616 135 608 145 600 155 C605 140 612 130 615 135 C618 140 610 155 600 170 Z" fill="#6b9e7a" opacity="0.25"/>
            <path d="M620 175 C620 160 628 145 635 138 C642 131 648 135 646 142 C644 149 638 158 632 165 Z" fill="#8cb89c" opacity="0.2"/>
          </svg>
          <span className="dashboard-ai-insight-accent" />
          <div className="dashboard-ai-insight-content">
            <div className="dashboard-ai-insight-header">
              <span className="dashboard-ai-insight-icon">
                <Sparkles size={16} />
              </span>
              <div className="dashboard-ai-insight-title-group">
                <h4>AI 洞察</h4>
                <span className="dashboard-ai-insight-badge">智能分析</span>
              </div>
            </div>
            <p className="dashboard-ai-insight-text">
              {overview?.daily_summary?.trim() ||
                "你最近连续三天都在研究 AI Agent 相关内容，是否生成一份学习路线图，帮你更系统地推进？"}
            </p>
            <div className="dashboard-ai-insight-actions">
              <Link className="dashboard-ai-insight-action" to="/app/insights">
                <Sparkles size={13} />
                生成路线图
                <ChevronRight size={14} />
              </Link>
              <Link className="dashboard-ai-insight-link" to="/app/insights">
                查看全部洞察
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* ── AI Panel ───────────────────────────────────────────────────────── */}
      <aside className={`ai-panel${aiOpen ? " open" : ""}`} aria-hidden={!aiOpen}>
        {/* Panel header */}
        <div className="ai-panel-header">
          <div className="ai-panel-header-title">
            <Sparkles size={16} />
            <span>AI 对话</span>
          </div>
          <div className="ai-panel-header-actions">
            <button
              className="ai-panel-new-btn"
              type="button"
              onClick={createNewSession}
              title="新建对话"
            >
              <Plus size={15} />
              新建对话
            </button>
            <button
              className="ai-panel-icon-btn"
              type="button"
              onClick={() => { cancelStream(); setAiOpen(false); }}
              aria-label="关闭对话面板"
              title="关闭"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Session search */}
        <div className="ai-panel-session-search">
          <Search size={14} />
          <input
            placeholder="搜索对话..."
            value={sessionSearch}
            onChange={(e) => setSessionSearch(e.target.value)}
          />
        </div>

        {/* Session list */}
        {filteredSessions.length > 0 && (
          <div className="ai-panel-session-list">
            {filteredSessions.map((s) => (
              <button
                key={s.session_id}
                type="button"
                className={`ai-panel-session-item${s.session_id === sessionId ? " active" : ""}`}
                onClick={() => switchSession(s)}
              >
                <div className="ai-panel-session-item-body">
                  <strong>{sessionPreview(s.title, s.context_type)}</strong>
                  <span className="ai-panel-session-preview">
                    {s.context_type === "global" ? "全局记忆对话" : `上下文：${s.context_type}`}
                  </span>
                </div>
                <span className="ai-panel-session-time">{formatSessionTime(s.created_at)}</span>
              </button>
            ))}
            {sessions && sessions.length > filteredSessions.length && (
              <div className="ai-panel-session-more">
                查看全部对话（{sessions.length}）
              </div>
            )}
          </div>
        )}

        {/* Divider */}
        {filteredSessions.length > 0 && <div className="ai-panel-divider" />}

        {/* Active session title */}
        {sessionId && (
          <div className="ai-panel-active-session">
            <Sparkles size={14} />
            <span>
              {sessions?.find((s) => s.session_id === sessionId)
                ? sessionPreview(
                    sessions.find((s) => s.session_id === sessionId)!.title,
                    sessions.find((s) => s.session_id === sessionId)!.context_type,
                  )
                : "当前对话"}
            </span>
          </div>
        )}

        {/* Chat messages */}
        <div className="ai-panel-messages">
          {chatMessages.length === 0 ? (
            <div className="ai-panel-empty">
              <Sparkles size={24} />
              <p>你好！有什么我可以帮你的？</p>
              <div className="ai-panel-suggestions">
                {[
                  "今天有什么需要关注的待办？",
                  "帮我总结最近的记录",
                  "有哪些重要提醒即将到期？",
                ].map((hint) => (
                  <button
                    key={hint}
                    type="button"
                    className="ai-panel-suggestion-chip"
                    onClick={() => submitQuestion(hint)}
                  >
                    {hint}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="ai-panel-turn-stack">
              {chatMessages.map((msg, idx) => (
                <div key={idx} className={`ai-panel-turn ${msg.role}`}>
                  <div className="ai-panel-turn-label">
                    {msg.role === "user" ? "你" : "MindMemo AI"}
                  </div>
                  <div className="ai-panel-turn-content">
                    {msg.role === "assistant" ? (
                      msg.content ? (
                        <MarkdownRenderer content={msg.content} />
                      ) : (
                        chatLoading && idx === chatMessages.length - 1 ? (
                          <div className="ai-panel-skeleton">
                            <span />
                            <span />
                            <span />
                          </div>
                        ) : null
                      )
                    ) : (
                      <p>{msg.content}</p>
                    )}
                  </div>
                </div>
              ))}
              {chatLoading && chatMessages[chatMessages.length - 1]?.role !== "assistant" && (
                <div className="ai-panel-skeleton">
                  <span />
                  <span />
                  <span />
                </div>
              )}
              <div ref={aiMessageEndRef} aria-hidden="true" />
            </div>
          )}
        </div>

        {/* Input */}
        <form
          className="ai-panel-input-area"
          onSubmit={(e) => { e.preventDefault(); submitQuestion(); }}
        >
          <div className="ai-panel-input-row">
            <Paperclip size={15} style={{ color: "#aaa", flexShrink: 0, cursor: "pointer" }} />
            <ImagePlus size={15} style={{ color: "#aaa", flexShrink: 0, cursor: "pointer" }} />
          </div>
          <div className="ai-panel-input-dock">
            <input
              ref={aiInputRef}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="输入你的问题..."
              disabled={chatLoading}
            />
            <button
              type="submit"
              disabled={!question.trim() || chatLoading}
              aria-label="发送"
              className="ai-panel-send-btn"
            >
              {chatLoading ? <Loader2 size={15} className="spin" /> : <Send size={15} />}
            </button>
          </div>
        </form>
      </aside>
    </div>
  );
}
