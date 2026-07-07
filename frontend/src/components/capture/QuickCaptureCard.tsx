import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell, CheckSquare, PencilLine } from "lucide-react";
import { api } from "../../api/client";

type CaptureMode = "memo" | "todo" | "reminder";

export function QuickCaptureCard() {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<CaptureMode>("memo");
  const [content, setContent] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [remindAt, setRemindAt] = useState("");
  const [message, setMessage] = useState("");

  const ingestText = useMutation({
    mutationFn: api.ingestText,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-reminders"] });
      queryClient.invalidateQueries({ queryKey: ["memories"] });
      queryClient.invalidateQueries({ queryKey: ["todos"] });
      queryClient.invalidateQueries({ queryKey: ["timeline"] });
      setContent("");
      setDueAt("");
      setRemindAt("");
      setMode("memo");
      const tips: Record<CaptureMode, string> = {
        memo: "已经帮你记下来了。",
        todo: "已经放进待办里了。",
        reminder: "已经设置好提醒了。",
      };
      setMessage(tips[mode]);
    },
  });

  function submitCapture() {
    const trimmed = content.trim();
    if (!trimmed) {
      return;
    }
    if (mode === "reminder" && !remindAt) {
      return;
    }

    setMessage("");
    ingestText.mutate({
      content: trimmed,
      record_type: mode,
      due_at: mode === "todo" && dueAt ? new Date(dueAt).toISOString() : null,
      remind_at: mode === "reminder" ? new Date(remindAt).toISOString() : null,
    });
  }

  function handleModeSwitch(next: CaptureMode) {
    setMode(next);
    setMessage("");
  }

  const allowSubmit =
    !ingestText.isPending &&
    content.trim().length > 0 &&
    (mode !== "reminder" || remindAt.length > 0);

  return (
    <section className="hero-panel">
      <div className="hero-copy">
        <span className="eyebrow">今天先记一件小事</span>
        <h3>不用想格式，先写下来就行。</h3>
        <p>像记在手机备忘录里一样自然。生活琐事、提醒、灵感、要办的事，都可以直接写。</p>
      </div>

      <div className="capture-modes" role="tablist" aria-label="记录模式">
        <button
          className={`mode-chip${mode === "memo" ? " active" : ""}`}
          type="button"
          onClick={() => handleModeSwitch("memo")}
        >
          <PencilLine size={16} />
          备忘
        </button>
        <button
          className={`mode-chip${mode === "todo" ? " active" : ""}`}
          type="button"
          onClick={() => handleModeSwitch("todo")}
        >
          <CheckSquare size={16} />
          待办
        </button>
        <button
          className={`mode-chip${mode === "reminder" ? " active" : ""}`}
          type="button"
          onClick={() => handleModeSwitch("reminder")}
        >
          <Bell size={16} />
          提醒
        </button>
      </div>

      <textarea
        className="capture-textarea"
        value={content}
        onChange={(event) => setContent(event.target.value)}
        placeholder={
          mode === "memo"
            ? "比如：周四下午去复查，记得带医保卡和上次化验单。"
            : mode === "todo"
              ? "比如：明天早上给房东发消息，顺便问一下这个月水费。"
              : "比如：周四下午三点去复查。"
        }
      />

      {mode === "todo" && (
        <div className="capture-datetime">
          <label>
            截止日期<span className="optional-tag">（可选）</span>
            <input
              type="datetime-local"
              value={dueAt}
              onChange={(e) => setDueAt(e.target.value)}
            />
          </label>
        </div>
      )}

      {mode === "reminder" && (
        <div className="capture-datetime">
          <label>
            提醒时间
            <input
              type="datetime-local"
              value={remindAt}
              onChange={(e) => setRemindAt(e.target.value)}
            />
          </label>
        </div>
      )}

      <div className="capture-footer">
        <div className="soft-note">
          {message ||
            (mode === "memo"
              ? "适合记生活琐事、提醒、想法。"
              : mode === "todo"
                ? "适合记必须处理、怕忘掉的事情。"
                : "设置提醒时间到点通知你。")}
        </div>
        <button className="button" type="button" disabled={!allowSubmit} onClick={submitCapture}>
          {ingestText.isPending
            ? "正在保存..."
            : mode === "memo"
              ? "记下来"
              : mode === "todo"
                ? "加入待办"
                : "设置提醒"}
        </button>
      </div>
    </section>
  );
}
