import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  BookOpen,
  Check,
  Clock,
  FileText,
  Loader2,
  MessageSquare,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Search,
  Send,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { api } from "../api/client";
import MarkdownRenderer from "../components/MarkdownRenderer";
import type { ChatSessionResponse } from "../api/types";
import "../styles/chat.css";

const MAX_VISIBLE_SESSIONS = 30;

function sessionPreview(title: string | null, contextType: string) {
  if (title) return title;
  if (contextType === "global") return "全局对话";
  return "新对话";
}

type SessionGroup = { label: string; items: ChatSessionResponse[] };

function groupSessions(list: ChatSessionResponse[]): SessionGroup[] {
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterdayStart = new Date(todayStart.getTime() - 86400000);
  const weekStart = new Date(todayStart.getTime() - 7 * 86400000);

  const groups: Record<string, ChatSessionResponse[]> = {
    "今天": [],
    "昨天": [],
    "近7天": [],
    "更早": [],
  };

  for (const s of list) {
    const d = new Date(s.created_at);
    if (d >= todayStart) groups["今天"].push(s);
    else if (d >= yesterdayStart) groups["昨天"].push(s);
    else if (d >= weekStart) groups["近7天"].push(s);
    else groups["更早"].push(s);
  }

  return (Object.entries(groups) as [string, ChatSessionResponse[]][])
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({ label, items }));
}

function formatTime(dateStr: string): string {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return "";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function ChatPage() {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const msgEndRef = useRef<HTMLDivElement | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [chatMessages, setChatMessages] = useState<{ role: string; content: string }[]>([]);
  const [chatLoading, setChatLoading] = useState(false);
  const [sessionSearch, setSessionSearch] = useState("");
  const [initialized, setInitialized] = useState(false);
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; sessionId: string } | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const renameInputRef = useRef<HTMLInputElement | null>(null);

  const { data: sessions, refetch: refetchSessions } = useQuery({
    queryKey: ["chat-sessions"],
    queryFn: () => api.listSessions(),
  });

  const filteredSessions = useMemo(() => {
    if (!sessions) return [];
    const base = sessionSearch.trim()
      ? sessions.filter((s) =>
          (s.title ?? "").toLowerCase().includes(sessionSearch.toLowerCase())
        )
      : sessions;
    return base.slice(0, MAX_VISIBLE_SESSIONS);
  }, [sessions, sessionSearch]);

  const grouped = useMemo(() => groupSessions(filteredSessions), [filteredSessions]);

  function cancelStream() {
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    setChatLoading(false);
  }

  async function loadMessages(sid: string) {
    try {
      const msgs = await api.getSessionMessages(sid);
      setChatMessages(msgs.map((m) => ({ role: m.role, content: m.content })));
    } catch {
      setChatMessages([]);
    }
  }

  useEffect(() => {
    if (initialized || !sessions) return;
    setInitialized(true);
    if (sessions.length > 0 && !sessionId) {
      const first = sessions[0];
      setSessionId(first.session_id);
      loadMessages(first.session_id);
    }
  }, [sessions, initialized, sessionId]);

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
    refetchSessions();
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  async function switchSession(s: ChatSessionResponse) {
    if (s.session_id === sessionId) return;
    cancelStream();
    setChatMessages([]);
    setSessionId(s.session_id);
    await loadMessages(s.session_id);
  }

  async function deleteSession(sid: string, e: React.MouseEvent) {
    e.stopPropagation();
    try {
      await api.deleteSession(sid);
      refetchSessions();
      if (sid === sessionId) {
        setChatMessages([]);
        setSessionId(null);
        const remaining = sessions?.filter((s) => s.session_id !== sid);
        if (remaining && remaining.length > 0) {
          setSessionId(remaining[0].session_id);
          await loadMessages(remaining[0].session_id);
        }
      }
    } catch {}
  }

  function handleContextMenu(e: React.MouseEvent, sid: string) {
    e.preventDefault();
    setCtxMenu({ x: e.clientX, y: e.clientY, sessionId: sid });
  }

  function closeCtxMenu() {
    setCtxMenu(null);
  }

  function startRename(sid: string, currentTitle: string) {
    setRenamingId(sid);
    setRenameValue(currentTitle || "");
    setCtxMenu(null);
    requestAnimationFrame(() => renameInputRef.current?.focus());
  }

  async function confirmRename(sid: string) {
    const title = renameValue.trim();
    if (title) {
      try {
        await api.updateSession(sid, { title });
        refetchSessions();
      } catch {}
    }
    setRenamingId(null);
    setRenameValue("");
  }

  async function togglePin(sid: string, currentPinned: boolean) {
    try {
      await api.updateSession(sid, { pinned: !currentPinned });
      refetchSessions();
    } catch {}
    setCtxMenu(null);
  }

  useEffect(() => {
    msgEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  async function submitQuestion(q = question) {
    const trimmed = q.trim();
    if (!trimmed || chatLoading) return;

    let sid = sessionId;
    if (!sid) {
      const s = await api.createOrGetSession({ context_type: "global", context_id: null, title: null });
      sid = s.session_id;
      setSessionId(sid);
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

  function handleInputKey(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submitQuestion();
    }
  }

  const activeSession = sessions?.find((s) => s.session_id === sessionId);
  const totalCount = sessions?.length ?? 0;

  return (
    <div className="chat-page">
      {/* ── Left: Session list ── */}
      <aside className="chat-sidebar">
        <div className="chat-sidebar-header">
          <h2>AI 对话</h2>
          <button className="chat-new-btn" type="button" onClick={createNewSession} title="新建对话">
            <Plus size={15} />
          </button>
        </div>

        <div className="chat-search">
          <Search size={14} />
          <input
            placeholder="搜索对话..."
            value={sessionSearch}
            onChange={(e) => setSessionSearch(e.target.value)}
          />
        </div>

        <div className="chat-session-list">
          {grouped.length === 0 ? (
            <div className="chat-session-empty">
              {sessionSearch ? "没有找到匹配的对话" : "还没有对话，点击 + 开始"}
            </div>
          ) : (
            grouped.map((group) => (
              <div key={group.label} className="chat-session-group">
                <div className="chat-session-group-label">{group.label}</div>
                {group.items.map((s) => (
                  renamingId === s.session_id ? (
                    <div key={s.session_id} className="chat-session-item renaming">
                      <input
                        ref={renameInputRef}
                        className="chat-rename-input"
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") confirmRename(s.session_id);
                          if (e.key === "Escape") { setRenamingId(null); setRenameValue(""); }
                        }}
                        onBlur={() => confirmRename(s.session_id)}
                        autoFocus
                      />
                    </div>
                  ) : (
                    <div
                      key={s.session_id}
                      className={`chat-session-item${s.session_id === sessionId ? " active" : ""}${s.pinned ? " pinned" : ""}`}
                      onClick={() => switchSession(s)}
                      onContextMenu={(e) => handleContextMenu(e, s.session_id)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => { if (e.key === "Enter") switchSession(s); }}
                    >
                      {s.pinned && <Pin size={12} className="chat-pin-icon" />}
                      <div className="chat-session-body">
                        <strong>{sessionPreview(s.title, s.context_type)}</strong>
                        {s.context_type !== "global" && (
                          <span className="chat-session-tag">{s.context_type}</span>
                        )}
                      </div>
                      <div className="chat-session-meta">
                        <span className="chat-session-time">{formatTime(s.created_at)}</span>
                        <button
                          className="chat-session-del"
                          type="button"
                          onClick={(e) => deleteSession(s.session_id, e)}
                          title="删除"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </div>
                  )
                ))}
              </div>
            ))
          )}
          {totalCount > MAX_VISIBLE_SESSIONS && (
            <div className="chat-session-more">显示最近 {MAX_VISIBLE_SESSIONS} 条，共 {totalCount} 条对话</div>
          )}
        </div>
      </aside>

      {/* ── Center: Active conversation ── */}
      <section className="chat-main">
        <div className="chat-main-header">
          <div className="chat-main-title">
            <Sparkles size={16} />
            <span>{activeSession ? sessionPreview(activeSession.title, activeSession.context_type) : "AI 对话"}</span>
          </div>
          {activeSession && (
            <span className="chat-main-date">
              <Clock size={13} />
              {new Date(activeSession.created_at).toLocaleString("zh-CN", { year: "numeric", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
        </div>

        <div className="chat-messages">
          {chatMessages.length === 0 ? (
            <div className="chat-empty">
              <div className="chat-empty-icon"><Sparkles size={28} /></div>
              <h3>你好！有什么我可以帮你的？</h3>
              <p>基于你的记录，我可以回答问题、总结知识、生成想法。</p>
              <div className="chat-suggestions">
                {[
                  "今天有什么需要关注的待办？",
                  "帮我总结最近的记录",
                  "有哪些重要提醒即将到期？",
                  "帮我梳理一下学习路线",
                ].map((hint) => (
                  <button
                    key={hint}
                    type="button"
                    className="chat-suggestion-chip"
                    onClick={() => submitQuestion(hint)}
                  >
                    {hint}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="chat-turns">
              {chatMessages.map((msg, idx) => (
                <div key={idx} className={`chat-turn ${msg.role}`}>
                  <div className="chat-turn-avatar">
                    {msg.role === "user" ? "你" : <Sparkles size={13} />}
                  </div>
                  <div className="chat-turn-body">
                    <div className="chat-turn-name">
                      {msg.role === "user" ? "你" : "MindMemo AI"}
                    </div>
                    <div className="chat-turn-content">
                      {msg.role === "assistant" ? (
                        msg.content ? (
                          <MarkdownRenderer content={msg.content} />
                        ) : chatLoading && idx === chatMessages.length - 1 ? (
                          <div className="chat-skeleton">
                            <span /><span /><span />
                          </div>
                        ) : null
                      ) : (
                        <p>{msg.content}</p>
                      )}
                    </div>
                  </div>
                </div>
              ))}
              {chatLoading && chatMessages[chatMessages.length - 1]?.role !== "assistant" && (
                <div className="chat-turn assistant">
                  <div className="chat-turn-avatar"><Sparkles size={13} /></div>
                  <div className="chat-turn-body">
                    <div className="chat-skeleton">
                      <span /><span /><span />
                    </div>
                  </div>
                </div>
              )}
              <div ref={msgEndRef} aria-hidden="true" />
            </div>
          )}
        </div>

        <form className="chat-input-bar" onSubmit={(e) => { e.preventDefault(); submitQuestion(); }}>
          <div className="chat-input-dock">
            <input
              ref={inputRef}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleInputKey}
              placeholder="输入你的问题..."
              disabled={chatLoading}
            />
            <button
              type="submit"
              disabled={!question.trim() || chatLoading}
              className="chat-send-btn"
              aria-label="发送"
            >
              {chatLoading ? <Loader2 size={15} className="spin" /> : <Send size={15} />}
            </button>
          </div>
        </form>
      </section>

      {/* ── Right: Context panel ── */}
      <aside className="chat-context">
        <div className="chat-ctx-section">
          <h4>对话上下文</h4>
          <div className="chat-ctx-list">
            <div className="chat-ctx-item">
              <MessageSquare size={14} />
              <div>
                <strong>全局记忆</strong>
                <span>所有记录参与对话</span>
              </div>
            </div>
          </div>
        </div>

        <div className="chat-ctx-section">
          <h4>AI 可能用到的内容</h4>
          <div className="chat-ctx-list">
            <div className="chat-ctx-item">
              <FileText size={14} />
              <div>
                <strong>最近的记录</strong>
                <span>AI 会参考你最新的笔记和文档</span>
              </div>
            </div>
            <div className="chat-ctx-item">
              <BookOpen size={14} />
              <div>
                <strong>知识库</strong>
                <span>已导入的文档和网页内容</span>
              </div>
            </div>
          </div>
        </div>

        <div className="chat-ctx-section">
          <h4>对话设置</h4>
          <div className="chat-settings-list">
            <div className="chat-setting-row">
              <span>关联记忆</span>
              <label className="chat-toggle">
                <input type="checkbox" defaultChecked />
                <span className="chat-toggle-track" />
              </label>
            </div>
            <p className="chat-setting-hint">基于你的记录提供个性化回答</p>
          </div>
        </div>
      </aside>
      {ctxMenu && (() => {
        const target = sessions?.find(s => s.session_id === ctxMenu.sessionId);
        return (
          <>
            <div className="chat-ctx-overlay" onClick={closeCtxMenu} onContextMenu={(e) => { e.preventDefault(); closeCtxMenu(); }} />
            <div className="chat-ctx-menu" style={{ left: ctxMenu.x, top: ctxMenu.y }}>
              <button className="chat-ctx-menu-item" onClick={() => startRename(ctxMenu.sessionId, target?.title || "")}>
                <Pencil size={14} />
                <span>重命名</span>
              </button>
              <button className="chat-ctx-menu-item" onClick={() => togglePin(ctxMenu.sessionId, target?.pinned ?? false)}>
                {target?.pinned ? <PinOff size={14} /> : <Pin size={14} />}
                <span>{target?.pinned ? "取消置顶" : "置顶"}</span>
              </button>
              <div className="chat-ctx-menu-divider" />
              <button className="chat-ctx-menu-item danger" onClick={(e) => { deleteSession(ctxMenu.sessionId, e); closeCtxMenu(); }}>
                <Trash2 size={14} />
                <span>删除</span>
              </button>
            </div>
          </>
        );
      })()}
    </div>
  );
}
