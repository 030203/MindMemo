import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "../api/client";
import { StatCard } from "../components/ui/StatCard";
import { formatDateTime, formatRiskLevel, formatTodoPriority, formatTodoStatus } from "../utils/presentation";

const statusOptions = [
  { value: "all", label: "全部" },
  { value: "pending", label: "待处理" },
  { value: "doing", label: "进行中" },
  { value: "blocked", label: "卡住了" },
  { value: "done", label: "已完成" },
];

const priorityOptions = [
  { value: "all", label: "所有优先级" },
  { value: "attention", label: "先看最要紧的" },
  { value: "urgent", label: "很急" },
  { value: "high", label: "重要" },
  { value: "medium", label: "普通" },
  { value: "low", label: "不着急" },
];

const sortOptions = [
  { value: "priority", label: "先看最要紧的" },
  { value: "newest", label: "先看最新加的" },
  { value: "due", label: "先看最近到期" },
] as const;

const editStatusOptions = [
  { value: "pending", label: "待处理" },
  { value: "doing", label: "进行中" },
  { value: "blocked", label: "卡住了" },
  { value: "done", label: "已完成" },
];

const editPriorityOptions = [
  { value: "urgent", label: "很急" },
  { value: "high", label: "重要" },
  { value: "medium", label: "普通" },
  { value: "low", label: "不着急" },
];

type TodoEditDraft = {
  title: string;
  description: string;
  priority: string;
  status: string;
  due_at: string | null;
  source_memory_id?: string | null;
};

function toDatetimeLocalValue(value: string | null) {
  if (!value) {
    return "";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  const hours = `${date.getHours()}`.padStart(2, "0");
  const minutes = `${date.getMinutes()}`.padStart(2, "0");
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function fromDatetimeLocalValue(value: string) {
  if (!value.trim()) {
    return null;
  }
  return new Date(value).toISOString();
}

export function TodosPage() {
  const queryClient = useQueryClient();
  const [searchInput, setSearchInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [status, setStatus] = useState("all");
  const [priority, setPriority] = useState("all");
  const [sort, setSort] = useState<(typeof sortOptions)[number]["value"]>("priority");
  const [editingTodoId, setEditingTodoId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<TodoEditDraft | null>(null);
  const [editError, setEditError] = useState("");

  const query = useMemo(
    () => ({
      q: keyword || undefined,
      status: status === "all" ? undefined : status,
      priority: priority === "all" ? undefined : priority,
      sort,
    }),
    [keyword, priority, sort, status],
  );

  const { data, isLoading, error } = useQuery({
    queryKey: ["todos", query],
    queryFn: () => api.listTodos(query),
  });

  const completeTodo = useMutation({
    mutationFn: api.completeTodo,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["todos"] });
      queryClient.invalidateQueries({ queryKey: ["timeline"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-reminders"] });
    },
  });

  const updateTodo = useMutation({
    mutationFn: ({ todoId, payload }: { todoId: string; payload: TodoEditDraft }) => api.updateTodo(todoId, payload),
    onSuccess: () => {
      setEditError("");
      setEditingTodoId(null);
      setEditDraft(null);
      queryClient.invalidateQueries({ queryKey: ["todos"] });
      queryClient.invalidateQueries({ queryKey: ["timeline"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-reminders"] });
    },
    onError: (mutationError) => {
      setEditError(mutationError instanceof Error ? mutationError.message : "保存失败，请稍后再试。");
    },
  });

  function handleSearchSubmit(event: FormEvent) {
    event.preventDefault();
    setKeyword(searchInput.trim());
  }

  function startEdit(todo: {
    id: string;
    title: string;
    description: string;
    priority: string;
    status: string;
    due_at: string | null;
    source_memory_id?: string | null;
  }) {
    setEditingTodoId(todo.id);
    setEditDraft({
      title: todo.title,
      description: todo.description,
      priority: todo.priority,
      status: todo.status,
      due_at: todo.due_at,
      source_memory_id: todo.source_memory_id ?? null,
    });
    setEditError("");
  }

  function cancelEdit() {
    setEditingTodoId(null);
    setEditDraft(null);
    setEditError("");
  }

  function saveEdit(todoId: string) {
    if (!editDraft) {
      return;
    }

    if (!editDraft.title.trim()) {
      setEditError("待办标题不能为空。");
      return;
    }

    setEditError("");
    updateTodo.mutate({
      todoId,
      payload: {
        ...editDraft,
        title: editDraft.title.trim(),
      },
    });
  }

  if (isLoading) {
    return <div className="loading">正在加载任务列表...</div>;
  }

  if (error || !data) {
    return <div className="error">任务加载失败。</div>;
  }

  const activeTodos = data.filter((item) => item.status !== "done");
  const doneTodos = data.filter((item) => item.status === "done");
  const attentionTodos = data.filter((item) => item.priority === "urgent" || item.priority === "high" || item.risk_level === "high");
  const hasFilter = Boolean(keyword) || status !== "all" || priority !== "all" || sort !== "priority";
  const selectedStatusLabel = statusOptions.find((item) => item.value === status)?.label ?? "全部";
  const selectedPriorityLabel = priorityOptions.find((item) => item.value === priority)?.label ?? "所有优先级";
  const selectedSortLabel = sortOptions.find((item) => item.value === sort)?.label ?? "先看最要紧的";

  return (
    <div className="page-grid">
      <section className="kpi-grid">
        <StatCard label="现在要处理" value={activeTodos.length} detail="当前筛选下还没完成的事" />
        <StatCard label="需要留心" value={attentionTodos.length} detail="高优先级或高风险事项" />
        <StatCard label="已经完成" value={doneTodos.length} detail="当前筛选下已经做完的事" />
      </section>

      <section className="panel">
        <div className="section-title">
          <h3>把待办理顺一点</h3>
          <span className="muted">{data.length} 条</span>
        </div>
        <p className="panel-subtitle">你可以按状态、优先级和关键词筛一下，再决定现在先做哪件事。</p>

        <form className="memory-filter-bar" onSubmit={handleSearchSubmit}>
          <label className="search-box" htmlFor="todo-search">
            <Search size={16} />
            <input
              id="todo-search"
              className="search-input"
              placeholder="搜待办标题或备注，比如：论文、面试、物业"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </label>
          <button className="button-ghost" type="submit">
            搜一下
          </button>
        </form>

        <div className="capture-modes" role="tablist" aria-label="待办状态筛选">
          {statusOptions.map((option) => (
            <button
              key={option.value}
              className={`mode-chip${status === option.value ? " active" : ""}`}
              type="button"
              onClick={() => setStatus(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>

        <div className="todo-toolbar">
          <div className="todo-toolbar-group">
            <label className="todo-toolbar-label" htmlFor="todo-priority-filter">
              优先级
            </label>
            <select id="todo-priority-filter" className="select" value={priority} onChange={(event) => setPriority(event.target.value)}>
              {priorityOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="todo-toolbar-group">
            <label className="todo-toolbar-label" htmlFor="todo-sort-mode">
              排序方式
            </label>
            <select
              id="todo-sort-mode"
              className="select"
              value={sort}
              onChange={(event) => setSort(event.target.value as (typeof sortOptions)[number]["value"])}
            >
              {sortOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {hasFilter ? (
          <div className="soft-note memory-filter-note">
            当前筛选：{selectedStatusLabel}，{selectedPriorityLabel}，{selectedSortLabel}
            {keyword ? `，关键词“${keyword}”` : ""}
          </div>
        ) : null}
      </section>

      <section className="panel">
        <div className="section-title">
          <h3>现在要处理的事</h3>
          <span className="muted">{activeTodos.length} 条</span>
        </div>
        <div className="list">
          {activeTodos.length === 0 ? (
            <div className="empty-state">
              {hasFilter ? "当前筛选下没有未完成待办了。可以换个条件看看，或者把筛选放宽一点。" : "暂时没有待办。脑子能清爽一点，挺不错。"}
            </div>
          ) : (
            activeTodos.map((item) => (
              <div className="list-item friendly-card" key={item.id}>
                <div className="list-item-header">
                  <div>
                    <strong>{item.title}</strong>
                    <p className="panel-subtitle">{item.description || "这条待办还没有补充细节。"}</p>
                  </div>
                  <span className="soft-tag">{formatTodoPriority(item.priority)}</span>
                </div>
                <div className="inline-meta">
                  <span>{formatTodoStatus(item.status)}</span>
                  <span>{formatRiskLevel(item.risk_level)}</span>
                  <span>{formatDateTime(item.due_at)}</span>
                </div>
                <div className="action-row">
                  <button className="button-ghost" type="button" onClick={() => startEdit(item)}>
                    编辑
                  </button>
                  <button className="button-ghost" type="button" onClick={() => completeTodo.mutate(item.id)}>
                    完成了
                  </button>
                </div>

                {editingTodoId === item.id && editDraft ? (
                  <div className="inline-edit-form">
                    <input
                      className="input"
                      value={editDraft.title}
                      onChange={(event) => setEditDraft((prev) => (prev ? { ...prev, title: event.target.value } : prev))}
                      placeholder="待办标题"
                    />
                    <textarea
                      className="textarea"
                      value={editDraft.description}
                      onChange={(event) => setEditDraft((prev) => (prev ? { ...prev, description: event.target.value } : prev))}
                      placeholder="补充这条待办的细节"
                    />
                    <div className="todo-toolbar">
                      <div className="todo-toolbar-group">
                        <label className="todo-toolbar-label">状态</label>
                        <select
                          className="select"
                          value={editDraft.status}
                          onChange={(event) => setEditDraft((prev) => (prev ? { ...prev, status: event.target.value } : prev))}
                        >
                          {editStatusOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="todo-toolbar-group">
                        <label className="todo-toolbar-label">优先级</label>
                        <select
                          className="select"
                          value={editDraft.priority}
                          onChange={(event) => setEditDraft((prev) => (prev ? { ...prev, priority: event.target.value } : prev))}
                        >
                          {editPriorityOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <div className="todo-toolbar-group">
                      <label className="todo-toolbar-label">提醒时间 / 截止时间</label>
                      <input
                        className="input"
                        type="datetime-local"
                        value={toDatetimeLocalValue(editDraft.due_at)}
                        onChange={(event) =>
                          setEditDraft((prev) => (prev ? { ...prev, due_at: fromDatetimeLocalValue(event.target.value) } : prev))
                        }
                      />
                    </div>
                    {editError ? <div className="error">{editError}</div> : null}
                    <div className="action-row">
                      <button className="button" type="button" onClick={() => saveEdit(item.id)} disabled={updateTodo.isPending}>
                        {updateTodo.isPending ? "正在保存..." : "保存修改"}
                      </button>
                      <button className="button-ghost" type="button" onClick={cancelEdit} disabled={updateTodo.isPending}>
                        取消
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            ))
          )}
        </div>
      </section>

      <section className="panel">
        <div className="section-title">
          <h3>已经做完的</h3>
          <span className="muted">{doneTodos.length} 条</span>
        </div>
        <div className="list">
          {doneTodos.length === 0 ? (
            <div className="empty-state">
              {hasFilter ? "当前筛选下还没有已完成的待办。" : "你完成的待办，会在这里留下一点痕迹。"}
            </div>
          ) : (
            doneTodos.map((item) => (
              <div className="list-item" key={item.id}>
                <div className="list-item-header">
                  <div>
                    <strong>{item.title}</strong>
                    <p className="panel-subtitle">{item.description || "已完成，没有补充说明。"}</p>
                  </div>
                  <span className="soft-tag">{formatTodoStatus(item.status)}</span>
                </div>
                <div className="inline-meta">
                  <span>{formatTodoPriority(item.priority)}</span>
                  <span>{formatDateTime(item.due_at)}</span>
                </div>
                <div className="action-row">
                  <button className="button-ghost" type="button" onClick={() => startEdit(item)}>
                    编辑
                  </button>
                </div>

                {editingTodoId === item.id && editDraft ? (
                  <div className="inline-edit-form">
                    <input
                      className="input"
                      value={editDraft.title}
                      onChange={(event) => setEditDraft((prev) => (prev ? { ...prev, title: event.target.value } : prev))}
                      placeholder="待办标题"
                    />
                    <textarea
                      className="textarea"
                      value={editDraft.description}
                      onChange={(event) => setEditDraft((prev) => (prev ? { ...prev, description: event.target.value } : prev))}
                      placeholder="补充这条待办的细节"
                    />
                    <div className="todo-toolbar">
                      <div className="todo-toolbar-group">
                        <label className="todo-toolbar-label">状态</label>
                        <select
                          className="select"
                          value={editDraft.status}
                          onChange={(event) => setEditDraft((prev) => (prev ? { ...prev, status: event.target.value } : prev))}
                        >
                          {editStatusOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div className="todo-toolbar-group">
                        <label className="todo-toolbar-label">优先级</label>
                        <select
                          className="select"
                          value={editDraft.priority}
                          onChange={(event) => setEditDraft((prev) => (prev ? { ...prev, priority: event.target.value } : prev))}
                        >
                          {editPriorityOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                    <div className="todo-toolbar-group">
                      <label className="todo-toolbar-label">提醒时间 / 截止时间</label>
                      <input
                        className="input"
                        type="datetime-local"
                        value={toDatetimeLocalValue(editDraft.due_at)}
                        onChange={(event) =>
                          setEditDraft((prev) => (prev ? { ...prev, due_at: fromDatetimeLocalValue(event.target.value) } : prev))
                        }
                      />
                    </div>
                    {editError ? <div className="error">{editError}</div> : null}
                    <div className="action-row">
                      <button className="button" type="button" onClick={() => saveEdit(item.id)} disabled={updateTodo.isPending}>
                        {updateTodo.isPending ? "正在保存..." : "保存修改"}
                      </button>
                      <button className="button-ghost" type="button" onClick={cancelEdit} disabled={updateTodo.isPending}>
                        取消
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
