import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileText, Link2, NotebookPen, CheckCircle2, ListTodo, Upload } from "lucide-react";
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
  const [memorySaved, setMemorySaved] = useState(false);
  const [todoSaved, setTodoSaved] = useState(false);
  const [urlSaved, setUrlSaved] = useState(false);
  const [pdfSaved, setPdfSaved] = useState(false);

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
      setMemorySaved(true);
      setTimeout(() => setMemorySaved(false), 2500);
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
      setTodoSaved(true);
      setTimeout(() => setTodoSaved(false), 2500);
    },
  });

  const ingestUrl = useMutation({
    mutationFn: api.ingestUrl,
    onSuccess: () => {
      refreshRelatedQueries();
      setUrlInput("");
      setUrlTitle("");
      setUrlSaved(true);
      setTimeout(() => setUrlSaved(false), 2500);
    },
  });

  const ingestPdf = useMutation({
    mutationFn: api.ingestPdf,
    onSuccess: () => {
      refreshRelatedQueries();
      setPdfTitle("");
      setPdfFile(null);
      setPdfSaved(true);
      setTimeout(() => setPdfSaved(false), 2500);
    },
  });

  function handleMemorySubmit(event: FormEvent) {
    event.preventDefault();
    const trimmedContent = memoryContent.trim();
    if (!trimmedContent) return;
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
    if (!trimmedTitle && !trimmedDescription) return;
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
    if (!normalizedUrl) return;
    ingestUrl.mutate({
      url: normalizedUrl,
      title: urlTitle.trim() || undefined,
      category: urlCategory,
    });
  }

  function handlePdfSubmit(event: FormEvent) {
    event.preventDefault();
    if (!pdfFile) return;
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
    <div className="ib-page">
      {/* ── Hero ── */}
      <section className="ib-hero">
        <div className="ib-hero-text">
          <span className="ib-eyebrow">轻一点开始</span>
          <h1>先记下来，剩下的交给系统整理。</h1>
          <p className="ib-hero-desc">
            写一条备忘、丢一个待办，或者把网页和 PDF 直接收进第二大脑里。
          </p>
        </div>
        <div className="ib-mode-chips">
          <span className="ib-mode-chip"><NotebookPen size={14} /> 文字记录</span>
          <span className="ib-mode-chip"><Link2 size={14} /> 网页收藏</span>
          <span className="ib-mode-chip"><FileText size={14} /> PDF 导入</span>
        </div>
      </section>

      {/* ── Split: Memory + Todo ── */}
      <div className="ib-split">
        {/* 写一条完整记录 */}
        <section className="ib-card">
          <div className="ib-card-header">
            <span className="ib-card-icon memo-icon">
              <NotebookPen size={18} />
            </span>
            <div className="ib-card-heading">
              <h3>写一条完整记录</h3>
            </div>
          </div>
          <p className="ib-card-desc">适合那些你想记得更完整的事情，比如安排、学习内容、项目进展。</p>
          <form className="ib-form" onSubmit={handleMemorySubmit}>
            <input
              className="ib-input"
              placeholder="标题可选，不写也可以"
              value={memoryTitle}
              onChange={(e) => setMemoryTitle(e.target.value)}
            />
            <select className="ib-select" value={memoryCategory} onChange={(e) => setMemoryCategory(e.target.value)}>
              {categoryOptions.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            <textarea
              className="ib-textarea"
              placeholder="比如：下周二下午三点去办证，记得带身份证和照片。"
              value={memoryContent}
              onChange={(e) => setMemoryContent(e.target.value)}
            />
            {createMemory.isError ? (
              <div className="ib-field-error">{(createMemory.error as Error).message}</div>
            ) : null}
            <button className="ib-submit-btn" type="submit" disabled={createMemory.isPending || !memoryContent.trim()}>
              {createMemory.isPending ? "正在保存..." : memorySaved ? "" : "保存这条记录"}
              {memorySaved && <><CheckCircle2 size={15} /> 已保存</>}
            </button>
          </form>
        </section>

        {/* 单独记一个待办 */}
        <section className="ib-card warm">
          <div className="ib-card-header">
            <span className="ib-card-icon todo-icon">
              <ListTodo size={18} />
            </span>
            <div className="ib-card-heading">
              <h3>单独记一个待办</h3>
            </div>
            <span className="ib-quick-tag">快速</span>
          </div>
          <p className="ib-card-desc">适合那些"必须做、别忘了"的小事。就算只写一句，也能先放进来。</p>
          <form className="ib-form" onSubmit={handleTodoSubmit}>
            <input
              className="ib-input"
              placeholder="比如：给物业打电话"
              value={todoTitle}
              onChange={(e) => setTodoTitle(e.target.value)}
            />
            <textarea
              className="ib-textarea"
              placeholder="补充细节也可以，比如：问停车费怎么交。"
              value={todoDescription}
              onChange={(e) => setTodoDescription(e.target.value)}
            />
            <div className="ib-form-row">
              <input
                className="ib-input"
                type="datetime-local"
                value={todoDueAt}
                onChange={(e) => setTodoDueAt(e.target.value)}
              />
              <select className="ib-select" value={todoPriority} onChange={(e) => setTodoPriority(e.target.value)}>
                <option value="low">不着急</option>
                <option value="medium">普通</option>
                <option value="high">重要</option>
                <option value="urgent">很急</option>
              </select>
            </div>
            {createTodo.isError ? (
              <div className="ib-field-error">{(createTodo.error as Error).message}</div>
            ) : null}
            <button
              className="ib-submit-btn"
              type="submit"
              disabled={createTodo.isPending || (!todoTitle.trim() && !todoDescription.trim())}
            >
              {createTodo.isPending ? "正在创建..." : todoSaved ? "" : "加入待办"}
              {todoSaved && <><CheckCircle2 size={15} /> 已加入</>}
            </button>
          </form>
        </section>
      </div>

      {/* ── Import section ── */}
      <section className="ib-import-section">
        <div className="ib-section-label">
          <div>
            <h2>导入资料</h2>
            <p>看到有用的网页或手头的 PDF，直接收进记忆系统。</p>
          </div>
        </div>

        <div className="ib-import-grid">
          {/* URL import */}
          <div className="ib-card">
            <div className="ib-card-header">
              <span className="ib-card-icon url-icon">
                <Link2 size={18} />
              </span>
              <div className="ib-card-heading">
                <h3>导入网页链接</h3>
              </div>
            </div>
            <p className="ib-card-desc">系统会尝试抓取正文、提取标题并写入长期记忆。</p>
            <form className="ib-form" onSubmit={handleUrlSubmit}>
              <input
                className="ib-input"
                placeholder="粘贴网页链接，例如 https://..."
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
              />
              <div className="ib-form-row">
                <input
                  className="ib-input"
                  placeholder="可选：自定义标题"
                  value={urlTitle}
                  onChange={(e) => setUrlTitle(e.target.value)}
                />
                <select className="ib-select" value={urlCategory} onChange={(e) => setUrlCategory(e.target.value)}>
                  {categoryOptions.map((o) => (
                    <option key={`url-${o.value}`} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
              {ingestUrl.isError ? (
                <div className="ib-field-error">{(ingestUrl.error as Error).message}</div>
              ) : null}
              <button className="ib-submit-btn" type="submit" disabled={ingestUrl.isPending || !urlInput.trim()}>
                {ingestUrl.isPending ? "正在导入..." : urlSaved ? "" : "导入网页"}
                {urlSaved && <><CheckCircle2 size={15} /> 已导入</>}
              </button>
            </form>
          </div>

          {/* PDF import */}
          <div className="ib-card">
            <div className="ib-card-header">
              <span className="ib-card-icon pdf-icon">
                <FileText size={18} />
              </span>
              <div className="ib-card-heading">
                <h3>导入 PDF</h3>
              </div>
            </div>
            <p className="ib-card-desc">适合论文、资料、方案文档。当前优先支持可复制文本的 PDF。</p>
            <form className="ib-form" onSubmit={handlePdfSubmit}>
              <label className="ib-file-field">
                <input type="file" accept="application/pdf,.pdf" onChange={handlePdfFileChange} />
                <span className="ib-file-label">
                  {pdfFile ? (
                    <>
                      <FileText size={20} />
                      <span className="ib-file-name">{pdfFile.name}</span>
                    </>
                  ) : (
                    <>
                      <Upload size={20} />
                      <span>点击选择 PDF 文件</span>
                    </>
                  )}
                </span>
              </label>
              <div className="ib-form-row">
                <input
                  className="ib-input"
                  placeholder="可选：自定义标题"
                  value={pdfTitle}
                  onChange={(e) => setPdfTitle(e.target.value)}
                />
                <select className="ib-select" value={pdfCategory} onChange={(e) => setPdfCategory(e.target.value)}>
                  {categoryOptions.map((o) => (
                    <option key={`pdf-${o.value}`} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </div>
              {ingestPdf.isError ? (
                <div className="ib-field-error">{(ingestPdf.error as Error).message}</div>
              ) : null}
              <button className="ib-submit-btn" type="submit" disabled={ingestPdf.isPending || !pdfFile}>
                {ingestPdf.isPending ? "正在解析..." : pdfSaved ? "" : "导入 PDF"}
                {pdfSaved && <><CheckCircle2 size={15} /> 已导入</>}
              </button>
            </form>
          </div>
        </div>
      </section>
    </div>
  );
}
