import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  CheckSquare,
  ChevronDown,
  Circle,
  Clock,
  Loader2,
  Search,
  X,
} from "lucide-react";
import { api } from "../api/client";
import { formatDateTime, formatTodoPriority, formatTodoStatus } from "../utils/presentation";
import "../styles/todos.css";

// ── config ────────────────────────────────────────────────────────────────────

const statusTabs = [
  { value: "all",     label: "全部" },
  { value: "pending", label: "待处理" },
  { value: "doing",   label: "进行中" },
  { value: "blocked", label: "卡住了" },
  { value: "done",    label: "已完成" },
];

const priorityOptions = [
  { value: "all",    label: "所有优先级" },
  { value: "urgent", label: "很急" },
  { value: "high",   label: "重要" },
  { value: "medium", label: "普通" },
  { value: "low",    label: "不着急" },
];

const sortOptions = [
  { value: "priority", label: "按优先级" },
  { value: "due",      label: "按截止时间" },
  { value: "newest",   label: "最新添加" },
] as const;

const editStatusOptions = [
  { value: "pending", label: "待处理" },
  { value: "doing",   label: "进行中" },
  { value: "blocked", label: "卡住了" },
  { value: "done",    label: "已完成" },
];

const editPriorityOptions = [
  { value: "urgent", label: "很急" },
  { value: "high",   label: "重要" },
  { value: "medium", label: "普通" },
  { value: "low",    label: "不着急" },
];

// ── helpers ───────────────────────────────────────────────────────────────────

const priorityMeta: Record<string, { dot: string; label: string }> = {
  urgent: { dot: "#dc2626", label: "很急" },
  high:   { dot: "#d97706", label: "重要" },
  medium: { dot: "#2563eb", label: "普通" },
  low:    { dot: "#9ca3af", label: "不着急" },
};

function PriorityDot({ priority }: { priority: string }) {
  return (
    <span
      className="td-priority-dot"
      style={{ background: priorityMeta[priority]?.dot ?? "#9ca3af" }}
    />
  );
}

function StatusIcon({ status }: { status: string }) {
  if (status === "done")    return <CheckCircle2 size={16} className="td-status-icon done" />;
  if (status === "doing")   return <Clock         size={16} className="td-status-icon doing" />;
  if (status === "blocked") return <AlertCircle   size={16} className="td-status-icon blocked" />;
  return <Circle size={16} className="td-status-icon pending" />;
}

function toDatetimeLocal(v: string | null) {
  if (!v) return "";
  const d = new Date(v);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}T${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
}

function fromDatetimeLocal(v: string) {
  return v.trim() ? new Date(v).toISOString() : null;
}

function dueBadge(due: string | null): { text: string; cls: string } | null {
  if (!due) return null;
  const d = new Date(/z|[+-]\d{2}:?\d{2}$/i.test(due) ? due : `${due}Z`);
  if (Number.isNaN(d.getTime())) return null;
  const diff = d.getTime() - Date.now();
  if (diff < 0)          return { text: "已逾期",  cls: "td-due-overdue" };
  if (diff < 86400000)   return { text: "今天到期", cls: "td-due-today" };
  if (diff < 172800000)  return { text: "明天到期", cls: "td-due-soon" };
  return { text: formatDateTime(due), cls: "td-due-normal" };
}

// ── types ─────────────────────────────────────────────────────────────────────

type Draft = {
  title: string; description: string; priority: string;
  status: string; due_at: string | null; source_memory_id?: string | null;
};

// ── Component ─────────────────────────────────────────────────────────────────

export function TodosPage() {
  const queryClient = useQueryClient();
  const [searchInput, setSearchInput] = useState("");
  const [keyword,     setKeyword]     = useState("");
  const [status,      setStatus]      = useState("all");
  const [priority,    setPriority]    = useState("all");
  const [sort,        setSort]        = useState<(typeof sortOptions)[number]["value"]>("priority");
  const [editId,      setEditId]      = useState<string | null>(null);
  const [draft,       setDraft]       = useState<Draft | null>(null);
  const [editErr,     setEditErr]     = useState("");

  const query = useMemo(() => ({
    q:        keyword  || undefined,
    status:   status   === "all" ? undefined : status,
    priority: priority === "all" ? undefined : priority,
    sort,
  }), [keyword, priority, sort, status]);

  const { data, isLoading, error } = useQuery({
    queryKey: ["todos", query],
    queryFn:  () => api.listTodos(query),
  });

  const completeMut = useMutation({
    mutationFn: api.completeTodo,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["todos"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-reminders"] });
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: Draft }) => api.updateTodo(id, payload),
    onSuccess: () => {
      setEditErr(""); setEditId(null); setDraft(null);
      queryClient.invalidateQueries({ queryKey: ["todos"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-reminders"] });
    },
    onError: (e) => setEditErr(e instanceof Error ? e.message : "保存失败"),
  });

  function handleSearch(e: FormEvent) {
    e.preventDefault();
    setKeyword(searchInput.trim());
  }

  function startEdit(t: { id:string; title:string; description:string; priority:string; status:string; due_at:string|null; source_memory_id?:string|null }) {
    setEditId(t.id);
    setDraft({ title:t.title, description:t.description, priority:t.priority, status:t.status, due_at:t.due_at, source_memory_id:t.source_memory_id??null });
    setEditErr("");
  }

  function cancelEdit() { setEditId(null); setDraft(null); setEditErr(""); }

  function saveEdit(id: string) {
    if (!draft) return;
    if (!draft.title.trim()) { setEditErr("待办标题不能为空"); return; }
    updateMut.mutate({ id, payload: { ...draft, title: draft.title.trim() } });
  }

  const todos        = data ?? [];
  const activeTodos  = todos.filter((t) => t.status !== "done");
  const doneTodos    = todos.filter((t) => t.status === "done");
  const urgentCount  = todos.filter((t) => t.priority === "urgent" || t.priority === "high").length;
  const hasFilter    = Boolean(keyword) || status !== "all" || priority !== "all";

  // ── edit form (shared) ────────────────────────────────────────────────────
  function EditForm({ id }: { id: string }) {
    if (!draft) return null;
    return (
      <div className="td-edit-form">
        <input className="td-input" value={draft.title} placeholder="待办标题"
          onChange={(e) => setDraft((p) => p ? { ...p, title: e.target.value } : p)} />
        <textarea className="td-textarea" value={draft.description} placeholder="补充细节（可选）" rows={3}
          onChange={(e) => setDraft((p) => p ? { ...p, description: e.target.value } : p)} />
        <div className="td-edit-row">
          <div className="td-field">
            <label className="td-field-label">状态</label>
            <div className="td-select-wrap">
              <select className="td-select" value={draft.status}
                onChange={(e) => setDraft((p) => p ? { ...p, status: e.target.value } : p)}>
                {editStatusOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <ChevronDown size={13} className="td-select-icon" />
            </div>
          </div>
          <div className="td-field">
            <label className="td-field-label">优先级</label>
            <div className="td-select-wrap">
              <select className="td-select" value={draft.priority}
                onChange={(e) => setDraft((p) => p ? { ...p, priority: e.target.value } : p)}>
                {editPriorityOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <ChevronDown size={13} className="td-select-icon" />
            </div>
          </div>
          <div className="td-field td-field-wide">
            <label className="td-field-label">截止时间</label>
            <input className="td-input" type="datetime-local"
              value={toDatetimeLocal(draft.due_at)}
              onChange={(e) => setDraft((p) => p ? { ...p, due_at: fromDatetimeLocal(e.target.value) } : p)} />
          </div>
        </div>
        {editErr && <div className="td-edit-error">{editErr}</div>}
        <div className="td-edit-actions">
          <button className="td-save-btn" type="button" onClick={() => saveEdit(id)} disabled={updateMut.isPending}>
            {updateMut.isPending ? <><Loader2 size={13} className="td-spin" /> 保存中…</> : "保存修改"}
          </button>
          <button className="td-cancel-btn" type="button" onClick={cancelEdit}>取消</button>
        </div>
      </div>
    );
  }

  // ── render ────────────────────────────────────────────────────────────────
  return (
    <div className="td-page">

      {/* Header */}
      <div className="td-header">
        <div className="td-header-left">
          <CheckSquare size={20} className="td-header-icon" />
          <div>
            <h1 className="td-title">待办</h1>
            <p className="td-subtitle">按状态、优先级筛一下，再决定现在先做哪件事。</p>
          </div>
        </div>
        <div className="td-stat-row">
          <div className="td-stat-pill">
            <span className="td-stat-num">{activeTodos.length}</span>
            <span className="td-stat-label">未完成</span>
          </div>
          <div className="td-stat-pill urgent">
            <span className="td-stat-num">{urgentCount}</span>
            <span className="td-stat-label">需留心</span>
          </div>
          <div className="td-stat-pill done-pill">
            <span className="td-stat-num">{doneTodos.length}</span>
            <span className="td-stat-label">已完成</span>
          </div>
        </div>
      </div>

      {/* Toolbar */}
      <div className="td-toolbar">
        <form className="td-search" onSubmit={handleSearch} style={{ display:"flex", alignItems:"center", flex:1, minWidth:180 }}>
          <Search size={14} className="td-search-icon" />
          <input className="td-search-input" placeholder="搜标题或备注…"
            value={searchInput} onChange={(e) => setSearchInput(e.target.value)} />
          {searchInput && (
            <button type="button" className="td-search-clear"
              onClick={() => { setSearchInput(""); setKeyword(""); }}>
              <X size={13} />
            </button>
          )}
        </form>
        <div className="td-select-wrap">
          <select className="td-select" value={priority} onChange={(e) => setPriority(e.target.value)}>
            {priorityOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <ChevronDown size={13} className="td-select-icon" />
        </div>
        <div className="td-select-wrap">
          <select className="td-select" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
            {sortOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <ChevronDown size={13} className="td-select-icon" />
        </div>
      </div>

      {/* Status tabs */}
      <div className="td-tabs" role="tablist">
        {statusTabs.map((tab) => {
          const count = tab.value === "all" ? todos.length
            : tab.value === "done" ? doneTodos.length
            : todos.filter((t) => t.status === tab.value).length;
          return (
            <button key={tab.value} type="button" role="tab"
              aria-selected={status === tab.value}
              className={`td-tab${status === tab.value ? " active" : ""}`}
              onClick={() => setStatus(tab.value)}>
              {tab.label}
              <span className="td-tab-count">{count}</span>
            </button>
          );
        })}
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="td-loading">
          {[1,2,3].map((i) => <div key={i} className="td-skeleton" />)}
        </div>
      ) : error || !data ? (
        <div className="td-error">任务加载失败，请稍后重试。</div>
      ) : (
        <>
          {/* Active */}
          {(status === "all" || status !== "done") && (
            <section className="td-section">
              {status === "all" && (
                <div className="td-section-head">
                  <span className="td-section-label">未完成</span>
                  <span className="td-section-count">{activeTodos.length}</span>
                </div>
              )}
              {activeTodos.length === 0 ? (
                <div className="td-empty">
                  {hasFilter ? "当前筛选下没有未完成待办，换个条件试试。" : "暂时没有待办，可以轻松一下 ☕"}
                </div>
              ) : (
                <div className="td-list">
                  {activeTodos.map((item) => {
                    const due = dueBadge(item.due_at);
                    const isEditing = editId === item.id;
                    return (
                      <div key={item.id} className={`td-card${isEditing ? " editing" : ""}`}>
                        <div className="td-card-main">
                          <button type="button" className="td-check-btn"
                            title="标记完成" onClick={() => completeMut.mutate(item.id)}
                            disabled={completeMut.isPending}>
                            <StatusIcon status={item.status} />
                          </button>
                          <div className="td-card-body">
                            <div className="td-card-topline">
                              <PriorityDot priority={item.priority} />
                              <span className="td-card-priority">
                                {priorityMeta[item.priority]?.label ?? formatTodoPriority(item.priority)}
                              </span>
                              <span className="td-card-status-chip">{formatTodoStatus(item.status)}</span>
                              {due && <span className={`td-due-badge ${due.cls}`}>{due.text}</span>}
                            </div>
                            <h3 className="td-card-title">{item.title}</h3>
                            {item.description && <p className="td-card-desc">{item.description}</p>}
                          </div>
                          <div className="td-card-actions">
                            <button type="button" className="td-action-btn"
                              onClick={() => isEditing ? cancelEdit() : startEdit(item)}>
                              {isEditing ? "取消" : "编辑"}
                            </button>
                          </div>
                        </div>
                        {isEditing && <EditForm id={item.id} />}
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
          )}

          {/* Done */}
          {(status === "all" || status === "done") && doneTodos.length > 0 && (
            <section className="td-section">
              <div className="td-section-head">
                <span className="td-section-label done">已完成</span>
                <span className="td-section-count">{doneTodos.length}</span>
              </div>
              <div className="td-list">
                {doneTodos.map((item) => {
                  const isEditing = editId === item.id;
                  return (
                    <div key={item.id} className={`td-card done${isEditing ? " editing" : ""}`}>
                      <div className="td-card-main">
                        <span className="td-check-btn done-static">
                          <CheckCircle2 size={16} className="td-status-icon done" />
                        </span>
                        <div className="td-card-body">
                          <div className="td-card-topline">
                            <span className="td-card-priority muted">
                              {priorityMeta[item.priority]?.label ?? formatTodoPriority(item.priority)}
                            </span>
                            {item.due_at && (
                              <span className="td-due-badge td-due-normal">{formatDateTime(item.due_at)}</span>
                            )}
                          </div>
                          <h3 className="td-card-title done">{item.title}</h3>
                          {item.description && <p className="td-card-desc">{item.description}</p>}
                        </div>
                        <div className="td-card-actions">
                          <button type="button" className="td-action-btn"
                            onClick={() => isEditing ? cancelEdit() : startEdit(item)}>
                            {isEditing ? "取消" : "编辑"}
                          </button>
                        </div>
                      </div>
                      {isEditing && <EditForm id={item.id} />}
                    </div>
                  );
                })}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
