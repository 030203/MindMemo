import { useEffect, useRef, useState, useCallback } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { Loader2, MessageSquare, Plus, Send, Sparkles, X } from "lucide-react";
import { api } from "../api/client";
import MarkdownRenderer from "./MarkdownRenderer";

interface AiChatModalProps {
  memoryId: string;
  memoryTitle: string;
  onClose: () => void;
}

export function AiChatModal({ memoryId, memoryTitle, onClose }: AiChatModalProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const msgEndRef = useRef<HTMLDivElement | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([]);
  const [loading, setLoading] = useState(false);

  function cancelStream() {
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    setLoading(false);
  }

  async function loadMessages(sid: string) {
    try {
      const msgs = await api.getSessionMessages(sid);
      setMessages(msgs.map((m) => ({ role: m.role, content: m.content })));
    } catch {
      setMessages([]);
    }
  }

  const initSession = useCallback(async () => {
    cancelStream();
    setMessages([]);
    setQuestion("");
    const s = await api.createOrGetSession({
      context_type: "memory",
      context_id: memoryId,
      title: `关于「${memoryTitle}」的对话`,
    });
    setSessionId(s.session_id);
    await loadMessages(s.session_id);
  }, [memoryId, memoryTitle]);

  useEffect(() => {
    initSession();
    const frame = requestAnimationFrame(() => inputRef.current?.focus());
    return () => {
      cancelStream();
      cancelAnimationFrame(frame);
    };
  }, [initSession]);

  useEffect(() => {
    msgEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    function onKey(e: globalThis.KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit(q = question) {
    const trimmed = q.trim();
    if (!trimmed || loading) return;

    let sid = sessionId;
    if (!sid) {
      const s = await api.createOrGetSession({
        context_type: "memory",
        context_id: memoryId,
        title: `关于「${memoryTitle}」的对话`,
      });
      sid = s.session_id;
      setSessionId(sid);
    }

    setQuestion("");
    const assistIdx = messages.length + 1;
    setMessages((prev) => [
      ...prev,
      { role: "user", content: trimmed },
      { role: "assistant", content: "" },
    ]);
    setLoading(true);

    let full = "";
    const ctrl = new AbortController();
    streamAbortRef.current = ctrl;
    api.askInSessionStream(
      sid,
      { question: trimmed },
      (chunk) => {
        full += chunk;
        setMessages((prev) =>
          prev.map((m, i) => (i === assistIdx ? { ...m, content: full } : m))
        );
      },
      () => {
        setLoading(false);
        streamAbortRef.current = null;
      },
      () => {
        setLoading(false);
        streamAbortRef.current = null;
      },
      ctrl.signal,
    );
  }

  async function newSession() {
    cancelStream();
    setMessages([]);
    setQuestion("");
    await initSession();
    requestAnimationFrame(() => inputRef.current?.focus());
  }

  function handleKey(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="aim-overlay" role="dialog" aria-modal="true">
      <div className="aim-backdrop" onClick={() => { cancelStream(); onClose(); }} />
      <div className="aim-panel">
        <div className="aim-header">
          <div className="aim-header-title">
            <Sparkles size={16} />
            <span>AI 对话</span>
          </div>
          <div className="aim-header-actions">
            <button className="aim-btn-new" type="button" onClick={newSession} title="新建对话">
              <Plus size={14} />
              <span>新建</span>
            </button>
            <button
              className="aim-btn-close"
              type="button"
              onClick={() => { cancelStream(); onClose(); }}
              aria-label="关闭"
              title="关闭"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="aim-context">
          <MessageSquare size={13} />
          <span>当前记录：</span>
          <strong>{memoryTitle}</strong>
        </div>

        <div className="aim-messages">
          {messages.length === 0 ? (
            <div className="aim-empty">
              <Sparkles size={22} />
              <p>针对这条记录，有什么想问 AI 的？</p>
              <div className="aim-suggestions">
                {[
                  "帮我总结这条记录的重点",
                  "基于这条记录给出行动建议",
                  "这条记录和我之前的哪些内容相关？",
                ].map((hint) => (
                  <button
                    key={hint}
                    type="button"
                    className="aim-suggestion-chip"
                    onClick={() => submit(hint)}
                  >
                    {hint}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="aim-turns">
              {messages.map((msg, idx) => (
                <div key={idx} className={`aim-turn ${msg.role}`}>
                  <div className="aim-turn-label">
                    {msg.role === "user" ? "你" : "MindMemo AI"}
                  </div>
                  <div className="aim-turn-content">
                    {msg.role === "assistant" ? (
                      msg.content ? (
                        <MarkdownRenderer content={msg.content} />
                      ) : loading && idx === messages.length - 1 ? (
                        <div className="aim-skeleton">
                          <span /><span /><span />
                        </div>
                      ) : null
                    ) : (
                      <p>{msg.content}</p>
                    )}
                  </div>
                </div>
              ))}
              {loading && messages[messages.length - 1]?.role !== "assistant" && (
                <div className="aim-skeleton">
                  <span /><span /><span />
                </div>
              )}
              <div ref={msgEndRef} aria-hidden="true" />
            </div>
          )}
        </div>

        <form className="aim-input" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <div className="aim-input-dock">
            <input
              ref={inputRef}
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleKey}
              placeholder="输入你的问题..."
              disabled={loading}
            />
            <button
              type="submit"
              disabled={!question.trim() || loading}
              aria-label="发送"
              className="aim-send-btn"
            >
              {loading ? <Loader2 size={14} className="spin" /> : <Send size={14} />}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
