import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, ClipboardEvent, KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  CheckCircle2,
  Clock3,
  FileUp,
  FileText,
  ImagePlus,
  Loader2,
  MessageCircle,
  Paperclip,
  Send,
  Sparkles,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { CitationItem, MemoryItem, TodoItem } from "../api/types";
import { isImageSource, resolveAssetUrl } from "../utils/media";
import { buildTitleFromText, formatDateTime } from "../utils/presentation";

type DraftAttachment = {
  id: string;
  file: File;
  previewUrl: string | null;
};

type FeedItem = {
  id: string;
  type: "memory" | "todo";
  title: string;
  body: string;
  sourceType?: string;
  fileName?: string | null;
  createdAt: string | null;
  dueAt: string | null;
  status?: string;
  priority?: string;
  memoryId?: string;
  imageUrl?: string;
  todo?: TodoItem;
};

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
  citations?: CitationItem[];
};

const quickReminderOptions = [
  { key: "today", label: "今天晚点" },
  { key: "tomorrow", label: "明天上午" },
  { key: "friday", label: "本周五" },
] as const;

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

function looksLikeTodo(text: string) {
  const normalized = text.trim().toLowerCase();
  return /待办|记得|提醒|要 |需要|完成|处理|提交|联系|打电话|周[一二三四五六日天]|明天|今天|ddl|todo/.test(normalized);
}

function isTextLikeFile(file: File) {
  const name = file.name.toLowerCase();
  return (
    file.type.startsWith("text/") ||
    [".md", ".markdown", ".txt", ".csv", ".json", ".yaml", ".yml", ".log"].some((extension) => name.endsWith(extension))
  );
}

function isReadableDocumentFile(file: File) {
  const name = file.name.toLowerCase();
  return (
    isTextLikeFile(file) ||
    name.endsWith(".docx") ||
    file.type === "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
  );
}

function nextReminderDate(key: (typeof quickReminderOptions)[number]["key"]) {
  const date = new Date();
  if (key === "today") {
    date.setHours(Math.max(date.getHours() + 3, 18), 0, 0, 0);
    return date.toISOString();
  }
  if (key === "tomorrow") {
    date.setDate(date.getDate() + 1);
    date.setHours(9, 0, 0, 0);
    return date.toISOString();
  }
  const day = date.getDay();
  const friday = 5;
  const offset = (friday - day + 7) % 7 || 7;
  date.setDate(date.getDate() + offset);
  date.setHours(17, 0, 0, 0);
  return date.toISOString();
}

function memoryToFeedItem(item: MemoryItem): FeedItem {
  return {
    id: `memory-${item.id}`,
    type: "memory",
    title: item.title || "未命名记录",
    body: item.content_summary || "这条记录还在整理摘要。",
    sourceType: item.source_type,
    fileName: item.file_name,
    createdAt: item.event_time,
    dueAt: item.due_time,
    memoryId: item.id,
    imageUrl: isImageSource({ sourceType: item.source_type, sourceUrl: item.source_url, fileName: item.file_name })
      ? resolveAssetUrl(item.source_url)
      : undefined,
  };
}

function todoToFeedItem(item: TodoItem): FeedItem {
  return {
    id: `todo-${item.id}`,
    type: "todo",
    title: item.title || "未命名待办",
    body: item.description || "没有补充说明。",
    createdAt: item.due_at,
    dueAt: item.due_at,
    status: item.status,
    priority: item.priority,
    memoryId: item.source_memory_id ?? undefined,
    todo: item,
  };
}

function compareFeedItems(left: FeedItem, right: FeedItem) {
  const leftTime = left.createdAt ? new Date(left.createdAt).getTime() : 0;
  const rightTime = right.createdAt ? new Date(right.createdAt).getTime() : 0;
  return rightTime - leftTime;
}

const documentFilePattern = /\.(md|markdown|txt|pdf|docx?|csv|json|yaml|yml|log)\b/i;
const documentMimePattern = /(text\/|application\/pdf|application\/msword|application\/vnd|officedocument|markdown|pdf|json|csv)/i;

function isDocumentFeedItem(item: FeedItem) {
  if (item.type !== "memory") {
    return false;
  }
  const combined = `${item.title}\n${item.body}\n${item.fileName ?? ""}`;
  return (
    ["file", "pdf", "url"].includes(item.sourceType ?? "") ||
    /^文件[:：]/.test(item.title.trim()) ||
    documentFilePattern.test(combined) ||
    (/附件[:：].*[（(].*[）)]/i.test(item.body) && documentMimePattern.test(item.body))
  );
}

export function DashboardPage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const aiInputRef = useRef<HTMLInputElement | null>(null);
  const aiMessageEndRef = useRef<HTMLDivElement | null>(null);
  const [draft, setDraft] = useState("");
  const [attachments, setAttachments] = useState<DraftAttachment[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [toast, setToast] = useState("");
  const [reminderTarget, setReminderTarget] = useState<FeedItem | null>(null);
  const [customReminderAt, setCustomReminderAt] = useState("");
  const [aiOpen, setAiOpen] = useState(false);
  const [selectedContext, setSelectedContext] = useState<FeedItem | null>(null);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);

  const { data: memories, isLoading: memoriesLoading } = useQuery({
    queryKey: ["memories", "home-feed"],
    queryFn: () => api.listMemories(),
  });
  const { data: todos, isLoading: todosLoading } = useQuery({
    queryKey: ["todos", "home-feed"],
    queryFn: () => api.listTodos({ sort: "priority" }),
  });

  useEffect(() => {
    const listener = () => {
      setSelectedContext(null);
      setMessages([]);
      setQuestion("");
      setAiOpen(true);
    };
    window.addEventListener("open-ai-drawer", listener);
    return () => window.removeEventListener("open-ai-drawer", listener);
  }, []);

  function refreshHome() {
    queryClient.invalidateQueries({ queryKey: ["memories"] });
    queryClient.invalidateQueries({ queryKey: ["todos"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard-reminders"] });
  }

  function addFiles(files: File[]) {
    const next = files.map((file) => ({
      id: crypto.randomUUID(),
      file,
      previewUrl: file.type.startsWith("image/") ? URL.createObjectURL(file) : null,
    }));
    setAttachments((current) => [...current, ...next]);
  }

  function removeAttachment(id: string) {
    setAttachments((current) => {
      const removed = current.find((item) => item.id === id);
      if (removed?.previewUrl) {
        URL.revokeObjectURL(removed.previewUrl);
      }
      return current.filter((item) => item.id !== id);
    });
  }

  const captureMutation = useMutation({
    mutationFn: async () => {
      const trimmed = draft.trim();
      const jobs: Promise<unknown>[] = [];

      if (trimmed) {
        if (looksLikeTodo(trimmed)) {
          jobs.push(
            api.createTodo({
              title: buildTitleFromText(trimmed, "新增待办"),
              description: trimmed,
              priority: "medium",
              due_at: null,
            }),
          );
        } else {
          jobs.push(
            api.createMemory({
              title: buildTitleFromText(trimmed, "随手记一条"),
              content: trimmed,
              category: "memo",
              source_type: "memo",
              run_ai_parse: true,
            }),
          );
        }
      }

      for (const attachment of attachments) {
        if (attachment.file.type === "application/pdf" || attachment.file.name.toLowerCase().endsWith(".pdf")) {
          const formData = new FormData();
          formData.append("file", attachment.file);
          formData.append("title", attachment.file.name);
          formData.append("category", "memo");
          jobs.push(api.ingestPdf(formData));
        } else if (attachment.file.type.startsWith("image/")) {
          const formData = new FormData();
          formData.append("file", attachment.file);
          formData.append("title", `截图：${attachment.file.name || "image.png"}`);
          formData.append("note", trimmed);
          formData.append("category", "memo");
          jobs.push(api.ingestImage(formData));
        } else if (isReadableDocumentFile(attachment.file)) {
          const formData = new FormData();
          formData.append("file", attachment.file);
          formData.append("category", "memo");
          if (trimmed) {
            formData.append("note", trimmed);
          }
          jobs.push(api.ingestDocument(formData));
        } else {
          jobs.push(
            api.createMemory({
              title: attachment.file.type.startsWith("image/") ? `截图：${attachment.file.name}` : `文件：${attachment.file.name}`,
              content: [trimmed, `附件：${attachment.file.name}（${attachment.file.type || "未知类型"}）`].filter(Boolean).join("\n\n"),
              category: "memo",
              source_type: "file",
              file_name: attachment.file.name,
              source_mime_type: attachment.file.type || "未知类型",
              run_ai_parse: true,
            }),
          );
        }
      }

      await Promise.all(jobs);
    },
    onSuccess: () => {
      attachments.forEach((item) => {
        if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
      });
      setDraft("");
      setAttachments([]);
      setToast("已保存到你的记录");
      refreshHome();
    },
  });

  const reminderMutation = useMutation({
    mutationFn: async ({ item, dueAt }: { item: FeedItem; dueAt: string }) => {
      if (item.type === "todo" && item.todo) {
        return api.updateTodo(item.todo.id, {
          title: item.todo.title,
          description: item.todo.description,
          priority: item.todo.priority,
          status: item.todo.status,
          due_at: dueAt,
          source_memory_id: item.todo.source_memory_id ?? null,
        });
      }
      return api.createTodo({
        title: `提醒：${item.title}`,
        description: item.body,
        priority: "medium",
        due_at: dueAt,
        source_memory_id: item.memoryId ?? null,
      });
    },
    onSuccess: () => {
      setReminderTarget(null);
      setCustomReminderAt("");
      setToast("提醒时间已设置");
      refreshHome();
    },
  });

  const deleteMemoryMutation = useMutation({
    mutationFn: api.deleteMemory,
    onSuccess: () => {
      setToast("记录已删除");
      setSelectedContext(null);
      refreshHome();
    },
  });

  const deleteTodoMutation = useMutation({
    mutationFn: api.deleteTodo,
    onSuccess: () => {
      setToast("待办已删除");
      setSelectedContext(null);
      refreshHome();
    },
  });

  const askMutation = useMutation({
    mutationFn: api.askQuestion,
    onSuccess: (data, variables) => {
      setMessages((current) => [
        ...current,
        { role: "user", content: variables.question },
        { role: "assistant", content: data.answer, citations: data.citations },
      ]);
      setQuestion("");
    },
  });

  useEffect(() => {
    if (!aiOpen) return;
    const frame = window.requestAnimationFrame(() => {
      aiInputRef.current?.focus();
      aiMessageEndRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [aiOpen, messages, askMutation.isPending, askMutation.isError, selectedContext?.id]);

  const feedItems = useMemo(() => {
    const memoryItems = (memories ?? []).slice(0, 16).map(memoryToFeedItem);
    const todoItems = (todos ?? []).filter((item) => item.status !== "done").slice(0, 12).map(todoToFeedItem);
    return [...memoryItems, ...todoItems].sort(compareFeedItems).slice(0, 24);
  }, [memories, todos]);

  const isSaving = captureMutation.isPending;
  const isLoadingFeed = memoriesLoading || todosLoading;

  function handleSubmitCapture() {
    if ((!draft.trim() && attachments.length === 0) || isSaving) return;
    setToast("");
    captureMutation.mutate();
  }

  function handleDraftKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSubmitCapture();
    }
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    addFiles(Array.from(event.target.files ?? []));
    event.target.value = "";
  }

  function handlePaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const files = Array.from(event.clipboardData.files);
    if (files.length > 0) {
      addFiles(files);
    }
  }

  function openAiForItem(item: FeedItem) {
    const isSameContext = selectedContext?.id === item.id;
    setSelectedContext(item);
    setAiOpen(true);
    setQuestion("");
    if (!isSameContext) {
      setMessages([]);
    }
  }

  function handleDeleteMemory(item: FeedItem) {
    if (!item.memoryId || deleteMemoryMutation.isPending) return;
    const confirmed = window.confirm(`确定删除这条记录吗？\n\n${item.title}`);
    if (!confirmed) return;
    deleteMemoryMutation.mutate(item.memoryId);
  }

  function handleDeleteItem(item: FeedItem) {
    if (item.type === "todo" && item.todo) {
      if (deleteTodoMutation.isPending) return;
      const confirmed = window.confirm(`确定删除这个待办吗？\n\n${item.title}`);
      if (!confirmed) return;
      deleteTodoMutation.mutate(item.todo.id);
      return;
    }
    handleDeleteMemory(item);
  }

  function openReminderPopover(item: FeedItem) {
    setReminderTarget(item);
    setCustomReminderAt(toDatetimeLocalValue(item.dueAt));
  }

  function submitCustomReminder(item: FeedItem) {
    const dueAt = fromDatetimeLocalValue(customReminderAt);
    if (!dueAt || reminderMutation.isPending) return;
    reminderMutation.mutate({ item, dueAt });
  }

  async function submitQuestion(nextQuestion = question) {
    const trimmed = nextQuestion.trim();
    if (!trimmed || askMutation.isPending) return;

    let baseContextText = selectedContext?.body || selectedContext?.title || "";

    if (selectedContext?.memoryId) {
      try {
        const detail = await queryClient.fetchQuery({
          queryKey: ["memory-detail", selectedContext.memoryId],
          queryFn: () => api.getMemoryDetail(selectedContext.memoryId!),
        });
        baseContextText = detail.content_raw?.trim() || detail.content_summary || baseContextText;
      } catch {
        // Fall back to the visible card summary if loading the full record fails.
      }
    }

    const contextText = selectedContext ? baseContextText : undefined;

    askMutation.mutate({
      question: trimmed,
      mode: "memory_only",
      context_title: selectedContext?.title,
      context_text: contextText,
    });
  }

  function openGlobalAi() {
    if (selectedContext) {
      setSelectedContext(null);
      setMessages([]);
      setQuestion("");
    }
    setAiOpen(true);
  }

  return (
    <div
      className={`home-workspace${isDragging ? " is-dragging" : ""}${aiOpen ? " ai-open" : ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setIsDragging(false);
        addFiles(Array.from(event.dataTransfer.files));
      }}
    >
      <div className="drop-overlay">
        <UploadCloud size={34} />
        <span>松手导入文件或截图</span>
      </div>

      <section className="super-input-section">
        <div className="super-input-copy">
          <span>Capture-first Memory</span>
          <h1>一个输入框，记下所有事。</h1>
          <p>写待办、灵感、链接，粘贴截图，拖入文件。回车保存，剩下的理解、检索和提醒交给后台。</p>
        </div>

        <div className="super-input-card">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleDraftKeyDown}
            onPaste={handlePaste}
            placeholder="写下任何事：周五前完成论文初稿、突然想到一个产品点子，或直接粘贴截图..."
          />

          {attachments.length > 0 ? (
            <div className="attachment-strip">
              {attachments.map((attachment) => (
                <div className="attachment-pill" key={attachment.id}>
                  {attachment.previewUrl ? <img src={attachment.previewUrl} alt={attachment.file.name} /> : <Paperclip size={15} />}
                  <span>{attachment.file.name}</span>
                  <button type="button" onClick={() => removeAttachment(attachment.id)} aria-label="移除附件">
                    <X size={13} />
                  </button>
                </div>
              ))}
            </div>
          ) : null}

          <div className="super-input-actions">
            <div className="super-input-tools">
              <button className="icon-text-button" type="button" onClick={() => fileInputRef.current?.click()}>
                <ImagePlus size={17} />
                截图
              </button>
              <button className="icon-text-button" type="button" onClick={() => fileInputRef.current?.click()}>
                <FileUp size={17} />
                文件
              </button>
              <input ref={fileInputRef} type="file" multiple hidden onChange={handleFileChange} />
            </div>
            <div className="super-input-submit">
              <span>{toast || (captureMutation.isError ? (captureMutation.error as Error).message : "Enter 保存，Shift + Enter 换行")}</span>
              <button className="send-button" type="button" disabled={isSaving || (!draft.trim() && attachments.length === 0)} onClick={handleSubmitCapture}>
                {isSaving ? <Loader2 className="spin" size={18} /> : <Send size={18} />}
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="record-flow-section">
        <div className="record-flow-heading">
          <div>
            <span>最近记录</span>
            <h2>自然流，不需要分类。</h2>
          </div>
          <button className="icon-text-button" type="button" onClick={openGlobalAi}>
            <MessageCircle size={17} />
            我想问 AI
          </button>
        </div>

        {isLoadingFeed ? <div className="loading">正在读取最近记录...</div> : null}
        {!isLoadingFeed && feedItems.length === 0 ? <div className="empty-state">先在上面写下一条内容，这里会出现你的记录流。</div> : null}

        <div className="record-masonry">
          {feedItems.map((item, index) => (
            <article className={`record-card record-card-${item.type} record-card-tone-${index % 6}`} key={item.id}>
              <div className="record-card-topline">
                <span>{item.type === "todo" ? "待办" : isDocumentFeedItem(item) ? "文件" : "记录"}</span>
                <div className="record-card-actions">
                  <button className="icon-button" type="button" onClick={() => openReminderPopover(item)} aria-label="设置提醒">
                    <Bell size={16} />
                  </button>
                  <button className="icon-button" type="button" onClick={() => openAiForItem(item)} aria-label="和 AI 聊聊">
                    <MessageCircle size={16} />
                  </button>
                  <button
                    className="icon-button danger-icon-button"
                    type="button"
                    onClick={() => handleDeleteItem(item)}
                    disabled={(item.type === "todo" && deleteTodoMutation.isPending) || (item.type !== "todo" && (!item.memoryId || deleteMemoryMutation.isPending))}
                    aria-label={item.type === "todo" ? "删除待办" : "删除记录"}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>

              {item.type === "todo" ? (
                <div className="todo-card-title">
                  <CheckCircle2 size={18} />
                  <h3>{item.title}</h3>
                </div>
              ) : (
                <h3>
                  {item.memoryId ? (
                    <Link className="record-title-link" to={`/app/memories/${item.memoryId}`}>
                      {item.title}
                    </Link>
                  ) : (
                    item.title
                  )}
                </h3>
              )}
              <div className="record-card-content">
                {isDocumentFeedItem(item) ? (
                  <Link className="record-document-chip" to={`/app/memories/${item.memoryId}`}>
                    <FileText size={14} />
                    打开文档阅读
                  </Link>
                ) : null}
                <p>{item.body}</p>
                {item.imageUrl ? (
                  <Link className="record-card-image-link" to={`/app/memories/${item.memoryId}`}>
                    <img className="record-card-image" src={item.imageUrl} alt={item.title} />
                  </Link>
                ) : null}
              </div>

              <div className="record-card-meta">
                <span>
                  <Clock3 size={14} />
                  {formatDateTime(item.dueAt ?? item.createdAt)}
                </span>
                {item.memoryId ? <Link to={`/app/memories/${item.memoryId}`}>查看原文</Link> : null}
              </div>

              {reminderTarget?.id === item.id ? (
                <div className="reminder-popover">
                  <span>提醒我</span>
                  {quickReminderOptions.map((option) => (
                    <button
                      key={option.key}
                      type="button"
                      disabled={reminderMutation.isPending}
                      onClick={() => reminderMutation.mutate({ item, dueAt: nextReminderDate(option.key) })}
                    >
                      {option.label}
                    </button>
                  ))}
                  <label className="reminder-custom-field">
                    <span>自定义时间</span>
                    <input
                      type="datetime-local"
                      value={customReminderAt}
                      min={toDatetimeLocalValue(new Date().toISOString())}
                      onChange={(event) => setCustomReminderAt(event.target.value)}
                    />
                  </label>
                  <div className="reminder-custom-actions">
                    <button
                      type="button"
                      disabled={!customReminderAt || reminderMutation.isPending}
                      onClick={() => submitCustomReminder(item)}
                    >
                      保存
                    </button>
                    <button
                      type="button"
                      disabled={reminderMutation.isPending}
                      onClick={() => {
                        setReminderTarget(null);
                        setCustomReminderAt("");
                      }}
                    >
                      取消
                    </button>
                  </div>
                </div>
              ) : null}
            </article>
          ))}
        </div>
      </section>

      <button
        className="ai-fab"
        type="button"
        onClick={openGlobalAi}
        aria-label="打开 AI 对话"
      >
        <Sparkles size={20} />
      </button>

      <aside className={`ai-drawer${aiOpen ? " open" : ""}`} aria-hidden={!aiOpen}>
        <div className="ai-drawer-header">
          <div>
            <span>AI Assistant</span>
            <h2>{selectedContext ? "我正在看这条记录。" : "我已读取你的最新记录。"}</h2>
          </div>
          <button className="icon-button" type="button" onClick={() => setAiOpen(false)} aria-label="关闭 AI 对话">
            <X size={18} />
          </button>
        </div>

        {selectedContext ? (
          <div className="ai-context-card">
            <span>{selectedContext.type === "todo" ? "待办上下文" : isDocumentFeedItem(selectedContext) ? "文档上下文" : "记录上下文"}</span>
            <strong>{selectedContext.title}</strong>
            <p>{selectedContext.body}</p>
            {selectedContext.memoryId ? <Link to={`/app/memories/${selectedContext.memoryId}`}>打开详情阅读</Link> : null}
          </div>
        ) : (
          <div className="ai-context-card">
            <span>上下文记忆</span>
            <strong>最近 {feedItems.length} 条记录已可参考</strong>
            <p>你可以直接问“我最近还有什么没处理？”或“把刚才的想法拆成步骤”。</p>
          </div>
        )}

        <div className="ai-message-list">
          {messages.length === 0 ? (
            <div className="ai-empty">想聊点什么？我会尽量带着你的最新记录一起回答。</div>
          ) : (
            messages.map((message, index) => (
              <div className={`ai-message ${message.role}`} key={`${message.role}-${index}`}>
                <p>{message.content}</p>
                {message.citations && message.citations.length > 0 ? (
                  <div className="ai-citations">
                    {message.citations.slice(0, 4).map((citation) =>
                      citation.type === "memory" ? (
                        <Link key={`${citation.type}-${citation.id}`} to={`/app/memories/${citation.id}`}>
                          {citation.title}
                        </Link>
                      ) : citation.type === "todo" ? (
                        <Link key={`${citation.type}-${citation.id}`} to="/todos">
                          {citation.title}
                        </Link>
                      ) : citation.type === "web" ? (
                        <a key={`${citation.type}-${citation.id}`} href={citation.id} target="_blank" rel="noreferrer">
                          {citation.title}
                        </a>
                      ) : (
                        <span key={`${citation.type}-${citation.id}`}>{citation.title}</span>
                      ),
                    )}
                  </div>
                ) : null}
              </div>
            ))
          )}
          {askMutation.isPending ? <div className="ai-message assistant">正在结合你的记录思考...</div> : null}
          {askMutation.isError ? <div className="error">{(askMutation.error as Error).message}</div> : null}
          <div ref={aiMessageEndRef} aria-hidden="true" />
        </div>

        <div className="ai-quick-row">
          {["总结一下", "拆成待办", "什么时候提醒我"].map((item) => (
            <button key={item} type="button" onClick={() => submitQuestion(item)}>
              {item}
            </button>
          ))}
        </div>

        <form
          className="ai-input"
          onSubmit={(event) => {
            event.preventDefault();
            submitQuestion();
          }}
        >
          <input ref={aiInputRef} value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="问问这条记录，或问你的最近记录..." />
          <button type="submit" disabled={!question.trim() || askMutation.isPending} aria-label="发送">
            <Send size={17} />
          </button>
        </form>
      </aside>
    </div>
  );
}
