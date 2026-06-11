import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileText, Link2, NotebookPen } from "lucide-react";
import { api } from "../api/client";
import { buildTitleFromText } from "../utils/presentation";

const categoryOptions = [
  { value: "memo", label: "随手记" },
  { value: "learning", label: "学习记录" },
  { value: "project", label: "项目进展" },
  { value: "idea", label: "灵感" },
];

export function InboxPage() {
  const queryClient = useQueryClient();
  const [memoryTitle, setMemoryTitle] = useState("");
  const [memoryContent, setMemoryContent] = useState("");
  const [memoryCategory, setMemoryCategory] = useState("memo");
  const [todoTitle, setTodoTitle] = useState("");
  const [todoDescription, setTodoDescription] = useState("");
  const [todoPriority, setTodoPriority] = useState("medium");
  const [todoDueAt, setTodoDueAt] = useState("");
  const [urlInput, setUrlInput] = useState("");
  const [urlTitle, setUrlTitle] = useState("");
  const [urlCategory, setUrlCategory] = useState("learning");
  const [pdfTitle, setPdfTitle] = useState("");
  const [pdfCategory, setPdfCategory] = useState("learning");
  const [pdfFile, setPdfFile] = useState<File | null>(null);

  function refreshRelatedQueries() {
    queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
    queryClient.invalidateQueries({ queryKey: ["memories"] });
    queryClient.invalidateQueries({ queryKey: ["timeline"] });
  }

  const createMemory = useMutation({
    mutationFn: api.createMemory,
    onSuccess: () => {
      refreshRelatedQueries();
      setMemoryTitle("");
      setMemoryContent("");
    },
  });

  const createTodo = useMutation({
    mutationFn: api.createTodo,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-reminders"] });
      queryClient.invalidateQueries({ queryKey: ["todos"] });
      queryClient.invalidateQueries({ queryKey: ["timeline"] });
      setTodoTitle("");
      setTodoDescription("");
      setTodoDueAt("");
    },
  });

  const ingestUrl = useMutation({
    mutationFn: api.ingestUrl,
    onSuccess: () => {
      refreshRelatedQueries();
      setUrlInput("");
      setUrlTitle("");
    },
  });

  const ingestPdf = useMutation({
    mutationFn: api.ingestPdf,
    onSuccess: () => {
      refreshRelatedQueries();
      setPdfTitle("");
      setPdfFile(null);
    },
  });

  function handleMemorySubmit(event: FormEvent) {
    event.preventDefault();
    const trimmedContent = memoryContent.trim();
    if (!trimmedContent) {
      return;
    }

    createMemory.mutate({
      title: memoryTitle.trim() || buildTitleFromText(trimmedContent, "认真记一条"),
      content: trimmedContent,
      category: memoryCategory,
      source_type: "memo",
      run_ai_parse: true,
    });
  }

  function handleTodoSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmedDescription = todoDescription.trim();
    const trimmedTitle = todoTitle.trim();
    if (!trimmedTitle && !trimmedDescription) {
      return;
    }

    createTodo.mutate({
      title: trimmedTitle || buildTitleFromText(trimmedDescription, "新增待办"),
      description: trimmedDescription,
      priority: todoPriority,
      due_at: todoDueAt ? new Date(todoDueAt).toISOString() : null,
    });
  }

  function handleUrlSubmit(event: FormEvent) {
    event.preventDefault();
    const normalizedUrl = urlInput.trim();
    if (!normalizedUrl) {
      return;
    }

    ingestUrl.mutate({
      url: normalizedUrl,
      title: urlTitle.trim() || undefined,
      category: urlCategory,
    });
  }

  function handlePdfSubmit(event: FormEvent) {
    event.preventDefault();
    if (!pdfFile) {
      return;
    }

    const formData = new FormData();
    formData.append("file", pdfFile);
    formData.append("category", pdfCategory);
    if (pdfTitle.trim()) {
      formData.append("title", pdfTitle.trim());
    }
    ingestPdf.mutate(formData);
  }

  function handlePdfFileChange(event: ChangeEvent<HTMLInputElement>) {
    setPdfFile(event.target.files?.[0] ?? null);
  }

  return (
    <div className="page-grid">
      <section className="hero-panel">
        <div className="hero-copy">
          <span className="eyebrow">轻一点开始</span>
          <h3>先记下来，剩下的交给系统慢慢帮你整理。</h3>
          <p>
            这里是你最常用的入口。你可以写一条备忘、丢一个待办，或者把网页和 PDF 直接收进第二大脑里。
          </p>
        </div>
        <div className="capture-modes">
          <span className="mode-chip active">文字记录</span>
          <span className="mode-chip active">网页收藏</span>
          <span className="mode-chip active">PDF 导入</span>
        </div>
      </section>

      <div className="split-layout page-grid">
        <section className="panel">
          <div className="section-title">
            <h3>写一条完整记录</h3>
            <NotebookPen size={18} className="muted" />
          </div>
          <p className="panel-subtitle">适合那些你想记得更完整一点的事情，比如安排、学习内容、生活琐事和项目进展。</p>
          <form className="form-grid" onSubmit={handleMemorySubmit}>
            <input
              className="input"
              placeholder="标题可选，不写也可以"
              value={memoryTitle}
              onChange={(event) => setMemoryTitle(event.target.value)}
            />
            <select className="select" value={memoryCategory} onChange={(event) => setMemoryCategory(event.target.value)}>
              {categoryOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <textarea
              className="textarea"
              placeholder="比如：下周二下午三点去办证，记得带身份证和照片。"
              value={memoryContent}
              onChange={(event) => setMemoryContent(event.target.value)}
            />
            {createMemory.isError ? <div className="error">{(createMemory.error as Error).message}</div> : null}
            <button className="button" type="submit" disabled={createMemory.isPending || !memoryContent.trim()}>
              {createMemory.isPending ? "正在保存..." : "保存这条记录"}
            </button>
          </form>
        </section>

        <section className="panel warm-panel">
          <div className="section-title">
            <h3>单独记一个待办</h3>
            <span className="soft-tag">快速</span>
          </div>
          <p className="panel-subtitle">适合那些“必须做、别忘了”的小事。就算只写一句，也能先放进来。</p>
          <form className="form-grid" onSubmit={handleTodoSubmit}>
            <input
              className="input"
              placeholder="比如：给物业打电话"
              value={todoTitle}
              onChange={(event) => setTodoTitle(event.target.value)}
            />
            <textarea
              className="textarea"
              placeholder="补充细节也可以，比如：问停车费怎么交。"
              value={todoDescription}
              onChange={(event) => setTodoDescription(event.target.value)}
            />
            <input
              className="input"
              type="datetime-local"
              value={todoDueAt}
              onChange={(event) => setTodoDueAt(event.target.value)}
            />
            <select className="select" value={todoPriority} onChange={(event) => setTodoPriority(event.target.value)}>
              <option value="low">不着急</option>
              <option value="medium">普通</option>
              <option value="high">重要</option>
              <option value="urgent">很急</option>
            </select>
            {createTodo.isError ? <div className="error">{(createTodo.error as Error).message}</div> : null}
            <button
              className="button"
              type="submit"
              disabled={createTodo.isPending || (!todoTitle.trim() && !todoDescription.trim())}
            >
              {createTodo.isPending ? "正在创建..." : "加入待办"}
            </button>
          </form>
        </section>
      </div>

      <section className="panel">
        <div className="section-title">
          <div>
            <h3>导入资料</h3>
            <p className="panel-subtitle">看到有用的网页，或者手头有 PDF，就直接交给我收进记忆系统。</p>
          </div>
        </div>

        <div className="grid-2 ingest-grid">
          <form className="mini-panel" onSubmit={handleUrlSubmit}>
            <div className="mini-panel-title">
              <div className="mini-panel-icon">
                <Link2 size={18} />
              </div>
              <div>
                <strong>导入网页链接</strong>
                <p>系统会尝试抓取正文、提取标题并写入长期记忆。</p>
              </div>
            </div>
            <div className="form-grid">
              <input
                className="input"
                placeholder="粘贴网页链接，例如 https://example.com/article"
                value={urlInput}
                onChange={(event) => setUrlInput(event.target.value)}
              />
              <input
                className="input"
                placeholder="可选：自定义标题"
                value={urlTitle}
                onChange={(event) => setUrlTitle(event.target.value)}
              />
              <select className="select" value={urlCategory} onChange={(event) => setUrlCategory(event.target.value)}>
                {categoryOptions.map((option) => (
                  <option key={`url-${option.value}`} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              {ingestUrl.isError ? <div className="error">{(ingestUrl.error as Error).message}</div> : null}
              <button className="button" type="submit" disabled={ingestUrl.isPending || !urlInput.trim()}>
                {ingestUrl.isPending ? "正在导入..." : "导入网页"}
              </button>
            </div>
          </form>

          <form className="mini-panel" onSubmit={handlePdfSubmit}>
            <div className="mini-panel-title">
              <div className="mini-panel-icon">
                <FileText size={18} />
              </div>
              <div>
                <strong>导入 PDF</strong>
                <p>适合论文、资料、方案文档。当前优先支持可复制文本的 PDF。</p>
              </div>
            </div>
            <div className="form-grid">
              <label className="file-field">
                <span className="file-field-label">{pdfFile ? pdfFile.name : "选择一个 PDF 文件"}</span>
                <input type="file" accept="application/pdf,.pdf" onChange={handlePdfFileChange} />
              </label>
              <input
                className="input"
                placeholder="可选：自定义标题"
                value={pdfTitle}
                onChange={(event) => setPdfTitle(event.target.value)}
              />
              <select className="select" value={pdfCategory} onChange={(event) => setPdfCategory(event.target.value)}>
                {categoryOptions.map((option) => (
                  <option key={`pdf-${option.value}`} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              {ingestPdf.isError ? <div className="error">{(ingestPdf.error as Error).message}</div> : null}
              <button className="button" type="submit" disabled={ingestPdf.isPending || !pdfFile}>
                {ingestPdf.isPending ? "正在解析..." : "导入 PDF"}
              </button>
            </div>
          </form>
        </div>
      </section>
    </div>
  );
}
