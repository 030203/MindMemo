import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckSquare, PencilLine } from "lucide-react";
import { api } from "../../api/client";
import { buildTitleFromText } from "../../utils/presentation";

type CaptureMode = "memo" | "todo";

export function QuickCaptureCard() {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<CaptureMode>("memo");
  const [content, setContent] = useState("");
  const [message, setMessage] = useState("");

  const createMemory = useMutation({
    mutationFn: api.createMemory,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
      queryClient.invalidateQueries({ queryKey: ["memories"] });
      queryClient.invalidateQueries({ queryKey: ["timeline"] });
      setContent("");
      setMessage("已经帮你记下来了。");
    },
  });

  const createTodo = useMutation({
    mutationFn: api.createTodo,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
      queryClient.invalidateQueries({ queryKey: ["todos"] });
      queryClient.invalidateQueries({ queryKey: ["timeline"] });
      setContent("");
      setMessage("已经放进待办里了。");
    },
  });

  const isSubmitting = createMemory.isPending || createTodo.isPending;

  function submitCapture() {
    const trimmed = content.trim();
    if (!trimmed) {
      return;
    }

    setMessage("");

    if (mode === "memo") {
      createMemory.mutate({
        title: buildTitleFromText(trimmed, "随手记一条"),
        content: trimmed,
        category: "memo",
        source_type: "memo",
        run_ai_parse: true,
      });
      return;
    }

    createTodo.mutate({
      title: buildTitleFromText(trimmed, "新增待办"),
      description: trimmed,
      priority: "medium",
      due_at: null,
    });
  }

  return (
    <section className="hero-panel">
      <div className="hero-copy">
        <span className="eyebrow">今天先记一件小事</span>
        <h3>不用想格式，先写下来就行。</h3>
        <p>像记在手机备忘录里一样自然。生活琐事、提醒、灵感、要办的事，都可以直接写。</p>
      </div>

      <div className="capture-modes" role="tablist" aria-label="记录模式">
        <button className={`mode-chip${mode === "memo" ? " active" : ""}`} type="button" onClick={() => setMode("memo")}>
          <PencilLine size={16} />
          只是记一条
        </button>
        <button className={`mode-chip${mode === "todo" ? " active" : ""}`} type="button" onClick={() => setMode("todo")}>
          <CheckSquare size={16} />
          这是待办
        </button>
      </div>

      <textarea
        className="capture-textarea"
        value={content}
        onChange={(event) => setContent(event.target.value)}
        placeholder={
          mode === "memo"
            ? "比如：周四下午去复查，记得带医保卡和上次化验单。"
            : "比如：明天早上给房东发消息，顺便问一下这个月水费。"
        }
      />

      <div className="capture-footer">
        <div className="soft-note">
          {message || (mode === "memo" ? "适合记生活琐事、提醒、想法。" : "适合记必须处理、怕忘掉的事情。")}
        </div>
        <button className="button" type="button" disabled={isSubmitting || !content.trim()} onClick={submitCapture}>
          {isSubmitting ? "正在保存..." : mode === "memo" ? "记下来" : "加入待办"}
        </button>
      </div>
    </section>
  );
}
