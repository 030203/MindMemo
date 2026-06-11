import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarDays, ExternalLink, FileText, Hash, Image as ImageIcon, Link2, Network, PencilLine, Sparkles, Tags, Trash2 } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ExtractedFact, MemoryDetail } from "../api/types";
import { isImageSource, resolveAssetUrl } from "../utils/media";
import { describeImportance, formatCategory, formatDateTimeLong, formatMemoryStatus } from "../utils/presentation";

const categoryOptions = [
  { value: "memo", label: "随手记" },
  { value: "learning", label: "学习记录" },
  { value: "project", label: "项目进展" },
  { value: "idea", label: "灵感" },
];

const factTypeLabels: Record<string, string> = {
  expense: "消费",
  mood: "情绪 / 状态",
  learning: "学习主题",
  plan: "计划候选",
};

function formatSourceType(sourceType: string) {
  if (sourceType === "url") {
    return "网页导入";
  }
  if (sourceType === "pdf") {
    return "PDF 导入";
  }
  if (sourceType === "file") {
    return "文件导入";
  }
  if (sourceType === "image") {
    return "截图导入";
  }
  return "手动记录";
}

function formatRelationType(type: string) {
  const labels: Record<string, string> = {
    shared_fact: "结构化事实相近",
    shared_semantic_signal: "语义线索相近",
    same_category: "同类记忆",
    temporal_neighbor: "时间相邻",
    weak_context: "弱关联",
  };
  return labels[type] ?? type;
}

function formatFactPayload(fact: ExtractedFact) {
  const payload = fact.structured_payload;
  if (fact.fact_type === "expense") {
    const amount = typeof payload.amount === "number" ? `${payload.amount} 元` : "金额未知";
    const category = typeof payload.category === "string" ? payload.category : "other";
    return `${amount} · ${category}`;
  }
  if (fact.fact_type === "mood") {
    const label = typeof payload.label === "string" ? payload.label : fact.title;
    const valence = typeof payload.valence === "number" ? `情绪值 ${payload.valence}` : "情绪值未知";
    return `${label} · ${valence}`;
  }
  if (fact.fact_type === "learning") {
    const topics = Array.isArray(payload.topics) ? payload.topics.join(" / ") : "";
    return topics || "暂未识别具体主题";
  }
  if (fact.fact_type === "plan") {
    return typeof payload.due_time === "string" && payload.due_time ? `预计时间 ${formatDateTimeLong(payload.due_time)}` : "待确认时间";
  }
  return JSON.stringify(payload);
}

const documentFilePattern = /\.(md|markdown|txt|pdf|docx?|csv|json|yaml|yml|log)\b/i;
const documentMimePattern = /(text\/|application\/pdf|application\/msword|application\/vnd|officedocument|markdown|pdf|json|csv)/i;

function isDocumentSource(sourceType: string) {
  return ["file", "pdf", "url"].includes(sourceType);
}

function looksLikeDocumentMemory(memory: Pick<MemoryDetail, "source_type" | "title" | "content_raw" | "file_name" | "source_url">) {
  const title = memory.title.trim();
  const fileName = memory.file_name ?? "";
  const sourceUrl = memory.source_url ?? "";
  const combined = `${title}\n${memory.content_raw}\n${fileName}\n${sourceUrl}`;
  return (
    isDocumentSource(memory.source_type) ||
    /^文件[:：]/.test(title) ||
    documentFilePattern.test(combined) ||
    /附件[:：].*[（(].*[）)]/i.test(memory.content_raw) && documentMimePattern.test(memory.content_raw)
  );
}

function formatMemorySourceType(memory: Pick<MemoryDetail, "source_type" | "title" | "content_raw" | "file_name" | "source_url">) {
  if (looksLikeDocumentMemory(memory) && !isDocumentSource(memory.source_type)) {
    return "文件导入";
  }
  return formatSourceType(memory.source_type);
}

function getReadableDocumentText(content: string) {
  const lines = content.replace(/\r/g, "").split("\n");
  const filtered = lines.filter((line) => !/^附件[:：]/.test(line.trim()));
  return filtered.join("\n").trim();
}

function getAttachmentLine(content: string) {
  return content
    .replace(/\r/g, "")
    .split("\n")
    .find((line) => /^附件[:：]/.test(line.trim()))
    ?.trim();
}

export function MemoryDetailPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { memoryId = "" } = useParams();
  const [isEditing, setIsEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("memo");
  const [formError, setFormError] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["memory-detail", memoryId],
    queryFn: () => api.getMemoryDetail(memoryId),
    enabled: Boolean(memoryId),
  });

  const { data: relatedMemories = [], isLoading: isRelatedLoading } = useQuery({
    queryKey: ["memory-related", memoryId],
    queryFn: () => api.listRelatedMemories(memoryId),
    enabled: Boolean(memoryId),
  });

  useEffect(() => {
    if (!data) {
      return;
    }

    setTitle(data.title);
    setContent(data.content_raw);
    setCategory(data.category);
  }, [data]);

  const updateMemory = useMutation({
    mutationFn: () =>
      api.updateMemory(memoryId, {
        title: title.trim(),
        content,
        category,
      }),
    onSuccess: (updated) => {
      setFormError("");
      setIsEditing(false);
      queryClient.setQueryData(["memory-detail", memoryId], updated);
      queryClient.invalidateQueries({ queryKey: ["memories"] });
      queryClient.invalidateQueries({ queryKey: ["memory-related", memoryId] });
      queryClient.invalidateQueries({ queryKey: ["timeline"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
    },
    onError: (mutationError) => {
      setFormError(mutationError instanceof Error ? mutationError.message : "保存失败，请稍后再试。");
    },
  });

  const deleteMemory = useMutation({
    mutationFn: () => api.deleteMemory(memoryId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["memories"] });
      queryClient.invalidateQueries({ queryKey: ["todos"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard-overview"] });
      navigate("/");
    },
  });

  if (isLoading) {
    return <div className="loading">正在加载记录详情...</div>;
  }

  if (error || !data) {
    return <div className="error">记录详情加载失败。</div>;
  }

  const memory = data;
  const imagePreviewUrl = isImageSource({
    sourceType: memory.source_type,
    sourceUrl: memory.source_url,
    fileName: memory.file_name,
  })
    ? resolveAssetUrl(memory.source_url)
    : "";
  const resolvedSourceUrl = memory.source_url ? resolveAssetUrl(memory.source_url) : "";
  const isDocument = looksLikeDocumentMemory(memory);
  const documentText = isDocument ? getReadableDocumentText(memory.content_raw) : "";
  const hasReadableDocumentText = documentText.length > 0;
  const attachmentLine = getAttachmentLine(memory.content_raw);
  const looksLikeLegacyImage =
    !imagePreviewUrl && (/^截图[:：]/.test(memory.title) || /image\/(png|jpe?g|webp|gif|bmp)/i.test(memory.content_raw));

  function handleSave() {
    if (!title.trim()) {
      setFormError("标题不能为空。");
      return;
    }

    if (!content.trim()) {
      setFormError("记录内容不能为空。");
      return;
    }

    setFormError("");
    updateMemory.mutate();
  }

  function handleCancel() {
    setTitle(memory.title);
    setContent(memory.content_raw);
    setCategory(memory.category);
    setFormError("");
    setIsEditing(false);
  }

  function handleDelete() {
    const confirmed = window.confirm(`确定删除这条记录吗？\n\n${memory.title}`);
    if (!confirmed) return;
    deleteMemory.mutate();
  }

  return (
    <div className="memory-detail-page">
      <section className="memory-detail-hero">
        <div className="memory-detail-hero-main">
          <Link className="detail-back-link" to="/">
            <ArrowLeft size={16} />
            回到首页
          </Link>
          <div className="detail-chip-row">
            <span>{formatCategory(memory.category)}</span>
            <span>{formatMemorySourceType(memory)}</span>
            <span>{formatMemoryStatus(memory.status)}</span>
          </div>
          <h1>{memory.title}</h1>
          <p>{memory.content_summary}</p>
          <div className="detail-actions">
            <button className="button" type="button" onClick={() => setIsEditing((prev) => !prev)}>
              <PencilLine size={16} />
              {isEditing ? "收起编辑" : "编辑记录"}
            </button>
            <button className="button-ghost danger-button" type="button" onClick={handleDelete} disabled={deleteMemory.isPending}>
              <Trash2 size={16} />
              {deleteMemory.isPending ? "删除中..." : "删除记录"}
            </button>
          </div>
          {deleteMemory.isError ? <div className="error">删除失败，请稍后再试。</div> : null}
        </div>

        <aside className="memory-detail-hero-aside">
          <div className="detail-stat-card">
            <Sparkles size={18} />
            <div>
              <span>重要性</span>
              <strong>{describeImportance(memory.importance_score)}</strong>
            </div>
          </div>
          <div className="detail-stat-card">
            <CalendarDays size={18} />
            <div>
              <span>记录时间</span>
              <strong>{formatDateTimeLong(memory.event_time)}</strong>
            </div>
          </div>
          {memory.source_url || memory.file_name ? (
            <div className="detail-source-panel">
              <span>来源</span>
              {memory.source_url ? (
                <a className="source-link" href={resolvedSourceUrl} target="_blank" rel="noreferrer">
                  <Link2 size={16} />
                  <strong>{memory.source_url}</strong>
                  <ExternalLink size={14} />
                </a>
              ) : null}
              {memory.file_name ? (
                <div className="source-file">
                  {imagePreviewUrl ? <ImageIcon size={16} /> : <FileText size={16} />}
                  <strong>{memory.file_name}</strong>
                </div>
              ) : null}
            </div>
          ) : null}
        </aside>
      </section>

      {isEditing ? (
        <section className="memory-detail-surface memory-edit-surface">
          <div className="section-title">
            <h3>修改这条记录</h3>
          </div>
          <div className="form-grid">
            <input className="input" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="标题" />
            <select className="select" value={category} onChange={(event) => setCategory(event.target.value)}>
              {categoryOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <textarea className="textarea" value={content} onChange={(event) => setContent(event.target.value)} placeholder="把这条记录改成你真正想留下来的样子" />
            {formError ? <div className="error">{formError}</div> : null}
            <div className="action-row">
              <button className="button" type="button" onClick={handleSave} disabled={updateMemory.isPending}>
                {updateMemory.isPending ? "正在保存..." : "保存修改"}
              </button>
              <button className="button-ghost" type="button" onClick={handleCancel} disabled={updateMemory.isPending}>
                取消
              </button>
            </div>
          </div>
        </section>
      ) : null}

      {imagePreviewUrl ? (
        <section className="memory-detail-surface screenshot-preview-surface">
          <div className="detail-surface-title">
            <ImageIcon size={18} />
            <h3>截图预览</h3>
          </div>
          <a className="screenshot-preview-frame" href={imagePreviewUrl} target="_blank" rel="noreferrer">
            <img src={imagePreviewUrl} alt={memory.file_name ?? memory.title} />
          </a>
        </section>
      ) : looksLikeLegacyImage ? (
        <section className="memory-detail-surface screenshot-missing-surface">
          <div className="detail-surface-title">
            <ImageIcon size={18} />
            <h3>截图预览</h3>
          </div>
          <p>
            这条旧截图记录只保存了文件名，原图没有落盘，所以无法回显。现在开始新粘贴或上传的截图会保存为图片资产，并在这里直接展示。
          </p>
        </section>
      ) : null}

      {isDocument ? (
        <section className="memory-detail-surface document-reader-surface">
          <div className="detail-surface-title">
            <FileText size={18} />
            <h3>文档阅读</h3>
          </div>
          <div className="document-reader-toolbar">
            <span>{memory.file_name || memory.source_url || memory.title}</span>
            {memory.source_url ? (
              <a href={resolvedSourceUrl} target="_blank" rel="noreferrer">
                打开来源
                <ExternalLink size={14} />
              </a>
            ) : null}
          </div>
          {hasReadableDocumentText ? (
            <pre className="document-reader-body">{documentText}</pre>
          ) : (
            <div className="empty-state">这条旧文件记录只保存了附件信息，没有保存可阅读正文。重新导入这个文件后，MindMemo 会在这里展示正文，并且 AI 也能按全文阅读回答。</div>
          )}
        </section>
      ) : null}

      <section className="memory-detail-main-grid">
        <article className={`memory-detail-surface ${isDocument ? "file-info-surface" : "raw-record-surface"}`}>
          <div className="detail-surface-title">
            <FileText size={18} />
            <h3>{isDocument ? "文件信息" : "原文记录"}</h3>
          </div>
          {isDocument ? (
            <div className="file-info-list">
              <div className="file-info-row">
                <span>文件名</span>
                <strong>{memory.file_name || memory.title.replace(/^文件[:：]\s*/, "")}</strong>
              </div>
              <div className="file-info-row">
                <span>来源类型</span>
                <strong>{formatMemorySourceType(memory)}</strong>
              </div>
              <div className="file-info-row">
                <span>正文状态</span>
                <strong>{hasReadableDocumentText ? `已解析，约 ${documentText.length} 字` : "旧记录仅保存附件信息"}</strong>
              </div>
              {attachmentLine ? (
                <div className="file-info-row">
                  <span>附件</span>
                  <strong>{attachmentLine.replace(/^附件[:：]\s*/, "")}</strong>
                </div>
              ) : null}
            </div>
          ) : (
            <p className="detail-body">{memory.content_raw}</p>
          )}
        </article>
        <aside className="memory-detail-surface ai-facts-surface">
          <div className="detail-surface-title">
            <Sparkles size={18} />
            <h3>AI 理解结果</h3>
          </div>
          {memory.extracted_facts.length === 0 ? (
            <div className="empty-state">这条记录还没有抽取出结构化事实。</div>
          ) : (
            <div className="detail-fact-list">
              {memory.extracted_facts.map((fact) => (
                <div className="detail-fact-card" key={fact.id}>
                  <div className="list-item-header">
                    <strong>{fact.title}</strong>
                    <span>{factTypeLabels[fact.fact_type] ?? fact.fact_type}</span>
                  </div>
                  <p>{formatFactPayload(fact)}</p>
                  <div className="inline-meta">
                    <span>置信度 {Math.round(fact.confidence_score * 100)}%</span>
                    <span>{formatDateTimeLong(fact.event_time)}</span>
                    <span>{fact.source}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </aside>
      </section>

      <section className="memory-detail-surface related-memory-surface">
        <div className="section-title">
          <div>
            <div className="detail-surface-title">
              <Network size={18} />
              <h3>相关记忆</h3>
            </div>
            <p className="panel-subtitle">系统会把共享事实、主题、实体或时间线相近的内容连接起来，帮助后续 Agent 做上下文推理。</p>
          </div>
          <span className="detail-count-pill">
            <Network size={14} />
            {relatedMemories.length} 条
          </span>
        </div>
        {isRelatedLoading ? (
          <div className="empty-state">正在整理这条记忆的上下文关系...</div>
        ) : relatedMemories.length === 0 ? (
          <div className="empty-state">还没有明显相关的记忆。继续记录后，关系网络会慢慢变得更有用。</div>
        ) : (
          <div className="related-memory-grid">
            {relatedMemories.map((item) => (
              <Link className="related-memory-card" key={item.id} to={`/app/memories/${item.id}`}>
                <div className="list-item-header">
                  <strong>{item.title}</strong>
                  <span>{formatRelationType(item.relation_type)}</span>
                </div>
                <p>{item.content_summary}</p>
                <div className="inline-meta">
                  <span>关联度 {Math.round(item.score * 100)}%</span>
                  <span>{formatCategory(item.category)}</span>
                  <span>{formatDateTimeLong(item.event_time)}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>

      <section className="memory-detail-bottom-grid">
        <div className="memory-detail-surface">
          <div className="detail-surface-title">
            <Tags size={18} />
            <h3>系统整理出的重点</h3>
          </div>
          <div className="inline-meta">
            <span>{describeImportance(memory.importance_score)}</span>
            <span>{formatMemoryStatus(memory.status)}</span>
            <span>{formatDateTimeLong(memory.event_time)}</span>
          </div>
          <div className="tag-row">
            {memory.tags.length === 0 ? <span className="tag">暂时还没有标签</span> : memory.tags.map((tag) => <span className="tag" key={tag}>{tag}</span>)}
          </div>
        </div>
        <div className="memory-detail-surface">
          <div className="detail-surface-title">
            <Hash size={18} />
            <h3>关键词与实体</h3>
          </div>
          <div className="tag-row">
            {[...memory.keywords, ...memory.entities].length === 0 ? (
              <span className="tag">暂时还没有识别到</span>
            ) : (
              [...memory.keywords, ...memory.entities].map((item) => (
                <span className="tag" key={item}>
                  {item}
                </span>
              ))
            )}
          </div>
        </div>
      </section>
    </div>
  );
}
