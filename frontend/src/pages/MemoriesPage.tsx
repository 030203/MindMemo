import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  BookOpen,
  Brain,
  FileText,
  Lightbulb,
  Search,
  StickyNote,
  X,
} from "lucide-react";
import { api } from "../api/client";
import {
  formatCategory,
  formatDateTime,
  formatMemoryStatus,
} from "../utils/presentation";
import "../styles/memories.css";

// ── category config ─────────────────────────────────────────────────────────

const categoryOptions = [
  { value: "all", label: "全部", icon: null },
  { value: "memo", label: "随手记", icon: StickyNote },
  { value: "learning", label: "学习记录", icon: BookOpen },
  { value: "project", label: "项目进展", icon: FileText },
  { value: "idea", label: "灵感", icon: Lightbulb },
];

const categoryColorMap: Record<string, string> = {
  memo: "#6b9e7a",
  learning: "#5b8fa8",
  project: "#8b7bb5",
  idea: "#d4a053",
  todo: "#2d6a4f",
};

function categoryColor(cat: string) {
  return categoryColorMap[cat] ?? "#9ca3af";
}

// ── SVG illustrations per category ────────────────────────────────────

// Deterministic pseudo-random from string
function hashStr(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) { h = ((h << 5) - h + s.charCodeAt(i)) | 0; }
  return Math.abs(h);
}

const illustrationPool = [
  // 0: Leafy branch
  <svg viewBox="0 0 88 88" fill="none" className="mem-card-illus">
    <path d="M15 75 C22 58 30 45 40 32 C46 24 55 15 68 8" stroke="#6b9e7a" strokeWidth="2.2" strokeLinecap="round" opacity="0.55"/>
    <ellipse cx="28" cy="58" rx="14" ry="9" fill="#8cb89c" opacity="0.4" transform="rotate(-35 28 58)"/>
    <ellipse cx="40" cy="42" rx="12" ry="8" fill="#a8d5b8" opacity="0.35" transform="rotate(-25 40 42)"/>
    <ellipse cx="52" cy="26" rx="11" ry="7" fill="#6b9e7a" opacity="0.35" transform="rotate(-15 52 26)"/>
    <ellipse cx="22" cy="68" rx="10" ry="6" fill="#8cb89c" opacity="0.3" transform="rotate(-45 22 68)"/>
    <path d="M28 58 L23 52 M40 42 L35 36 M52 26 L48 20" stroke="#6b9e7a" strokeWidth="1.2" opacity="0.4"/>
    <circle cx="70" cy="10" r="4" fill="#a8d5b8" opacity="0.2"/>
    <circle cx="18" cy="72" r="3" fill="#8cb89c" opacity="0.2"/>
    <circle cx="60" cy="18" r="2" fill="#6b9e7a" opacity="0.15"/>
  </svg>,
  // 1: Coffee cup with steam
  <svg viewBox="0 0 88 88" fill="none" className="mem-card-illus">
    <rect x="22" y="35" width="38" height="35" rx="6" fill="#d4a053" opacity="0.3"/>
    <rect x="26" y="39" width="30" height="10" rx="3" fill="#fff" opacity="0.4"/>
    <path d="M60 45 C66 45 70 50 70 55 C70 60 66 65 60 65" stroke="#d4a053" strokeWidth="2.5" opacity="0.35" strokeLinecap="round"/>
    <rect x="20" y="70" width="42" height="4" rx="2" fill="#d4a053" opacity="0.2"/>
    <path d="M34 30 C34 24 36 18 38 14" stroke="#8cb89c" strokeWidth="1.8" strokeLinecap="round" opacity="0.3"/>
    <path d="M42 28 C42 22 44 16 46 12" stroke="#8cb89c" strokeWidth="1.8" strokeLinecap="round" opacity="0.25"/>
    <path d="M50 30 C50 24 52 18 54 14" stroke="#8cb89c" strokeWidth="1.8" strokeLinecap="round" opacity="0.2"/>
  </svg>,
  // 2: Mountain sunset
  <svg viewBox="0 0 88 88" fill="none" className="mem-card-illus">
    <circle cx="62" cy="22" r="12" fill="#d4a053" opacity="0.25"/>
    <circle cx="62" cy="22" r="7" fill="#d4a053" opacity="0.35"/>
    <path d="M0 70 L22 35 L38 52 L55 25 L72 45 L88 30 L88 88 L0 88 Z" fill="#8cb89c" opacity="0.3"/>
    <path d="M0 75 L18 52 L32 62 L48 40 L65 55 L88 42 L88 88 L0 88 Z" fill="#6b9e7a" opacity="0.22"/>
    <path d="M30 78 C32 68 38 60 48 55" stroke="#4a8a5e" strokeWidth="1.5" strokeLinecap="round" opacity="0.25" strokeDasharray="3 4"/>
    <path d="M14 60 C16 56 18 54 20 56 C22 58 20 60 18 60Z" fill="#6b9e7a" opacity="0.35"/>
    <path d="M66 50 C68 46 70 44 72 46 C74 48 72 50 70 50Z" fill="#6b9e7a" opacity="0.3"/>
  </svg>,
  // 3: Flower cluster
  <svg viewBox="0 0 88 88" fill="none" className="mem-card-illus">
    <path d="M44 80 C44 60 42 45 38 30 C36 22 40 14 44 10" stroke="#6b9e7a" strokeWidth="2" strokeLinecap="round" opacity="0.45"/>
    <path d="M44 50 C50 46 55 42 60 38" stroke="#6b9e7a" strokeWidth="1.5" strokeLinecap="round" opacity="0.35"/>
    <path d="M44 62 C38 58 33 54 28 50" stroke="#6b9e7a" strokeWidth="1.5" strokeLinecap="round" opacity="0.35"/>
    <circle cx="44" cy="12" r="8" fill="#d4a053" opacity="0.3"/>
    <circle cx="44" cy="12" r="4" fill="#d4a053" opacity="0.45"/>
    <circle cx="60" cy="36" r="7" fill="#8cb89c" opacity="0.3"/>
    <circle cx="60" cy="36" r="3.5" fill="#8cb89c" opacity="0.45"/>
    <circle cx="28" cy="48" r="6" fill="#a8d5b8" opacity="0.3"/>
    <circle cx="28" cy="48" r="3" fill="#a8d5b8" opacity="0.45"/>
    <circle cx="50" cy="24" r="4" fill="#d4a053" opacity="0.2"/>
    <circle cx="36" cy="36" r="3.5" fill="#8cb89c" opacity="0.2"/>
    <ellipse cx="44" cy="30" rx="5" ry="8" fill="#6b9e7a" opacity="0.2" transform="rotate(-10 44 30)"/>
    <ellipse cx="38" cy="55" rx="4" ry="7" fill="#6b9e7a" opacity="0.18" transform="rotate(15 38 55)"/>
  </svg>,
  // 4: Stacked papers/notes
  <svg viewBox="0 0 88 88" fill="none" className="mem-card-illus">
    <rect x="18" y="20" width="46" height="56" rx="5" fill="#8cb89c" opacity="0.15" transform="rotate(3 41 48)"/>
    <rect x="22" y="16" width="46" height="56" rx="5" fill="#a8d5b8" opacity="0.2" transform="rotate(-2 45 44)"/>
    <rect x="20" y="12" width="46" height="56" rx="5" fill="#fff" opacity="0.5" stroke="#8cb89c" strokeWidth="1" opacity="0.3"/>
    <rect x="28" y="22" width="28" height="3.5" rx="1.75" fill="#6b9e7a" opacity="0.5"/>
    <rect x="28" y="30" width="22" height="3" rx="1.5" fill="#6b9e7a" opacity="0.35"/>
    <rect x="28" y="37" width="18" height="3" rx="1.5" fill="#6b9e7a" opacity="0.25"/>
    <rect x="28" y="44" width="24" height="3" rx="1.5" fill="#6b9e7a" opacity="0.2"/>
    <circle cx="58" cy="56" r="7" fill="#6b9e7a" opacity="0.7"/>
    <path d="M55 56l2.5 2.5 4.5-4.5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>,
  // 5: Open book with bookmark
  <svg viewBox="0 0 88 88" fill="none" className="mem-card-illus">
    <path d="M8 68 C8 40 22 28 44 22 C66 28 80 40 80 68" fill="#d4e8d0" opacity="0.35"/>
    <path d="M44 22 L44 68" stroke="#6b9e7a" strokeWidth="1.5" opacity="0.3"/>
    <path d="M16 48 C22 44 32 42 42 44" stroke="#8cb89c" strokeWidth="1.2" opacity="0.4" strokeLinecap="round"/>
    <path d="M16 54 C22 50 32 48 42 50" stroke="#8cb89c" strokeWidth="1.2" opacity="0.3" strokeLinecap="round"/>
    <path d="M16 60 C22 56 32 54 42 56" stroke="#8cb89c" strokeWidth="1.2" opacity="0.25" strokeLinecap="round"/>
    <path d="M72 48 C66 44 56 42 46 44" stroke="#8cb89c" strokeWidth="1.2" opacity="0.4" strokeLinecap="round"/>
    <path d="M72 54 C66 50 56 48 46 50" stroke="#8cb89c" strokeWidth="1.2" opacity="0.3" strokeLinecap="round"/>
    <path d="M56 18 L56 34 L60 30 L64 34 L64 18" fill="#d4a053" opacity="0.45"/>
  </svg>,
  // 6: Pencil and ruler
  <svg viewBox="0 0 88 88" fill="none" className="mem-card-illus">
    <rect x="16" y="30" width="8" height="48" rx="2" fill="#d4a053" opacity="0.4" transform="rotate(-15 20 54)"/>
    <path d="M14.5 74 L20 82 L25.5 74" fill="#d4a053" opacity="0.55" transform="rotate(-15 20 78)"/>
    <rect x="18" y="30" width="4" height="8" rx="1" fill="#d4a053" opacity="0.6" transform="rotate(-15 20 34)"/>
    <rect x="40" y="18" width="12" height="56" rx="2" fill="#8cb89c" opacity="0.3" transform="rotate(8 46 46)"/>
    <line x1="42" y1="26" x2="50" y2="27" stroke="#6b9e7a" strokeWidth="1" opacity="0.35"/>
    <line x1="42" y1="34" x2="50" y2="35" stroke="#6b9e7a" strokeWidth="1" opacity="0.35"/>
    <line x1="42" y1="42" x2="50" y2="43" stroke="#6b9e7a" strokeWidth="1" opacity="0.35"/>
    <line x1="42" y1="50" x2="50" y2="51" stroke="#6b9e7a" strokeWidth="1" opacity="0.35"/>
    <line x1="42" y1="58" x2="50" y2="59" stroke="#6b9e7a" strokeWidth="1" opacity="0.35"/>
    <line x1="42" y1="66" x2="50" y2="67" stroke="#6b9e7a" strokeWidth="1" opacity="0.35"/>
  </svg>,
  // 7: Lightbulb with sparkles
  <svg viewBox="0 0 88 88" fill="none" className="mem-card-illus">
    <circle cx="44" cy="34" r="22" fill="#fef3c7" opacity="0.3"/>
    <path d="M44 12 C55 12 64 22 64 34 C64 43 57 48 53 54 L35 54 C31 48 24 43 24 34 C24 22 33 12 44 12Z" fill="#d4a053" opacity="0.45" stroke="#d4a053" strokeWidth="1.2" opacity="0.5"/>
    <rect x="35" y="56" width="18" height="5" rx="2.5" fill="#d4a053" opacity="0.4"/>
    <rect x="36" y="63" width="16" height="4" rx="2" fill="#d4a053" opacity="0.3"/>
    <rect x="37" y="69" width="14" height="4" rx="2" fill="#d4a053" opacity="0.25"/>
    <circle cx="44" cy="30" r="7" fill="#fff" opacity="0.45"/>
    <path d="M44 3v5M66 14l4-4M74 34h5M14 34h-5M22 14l-4-4" stroke="#d4a053" strokeWidth="2.5" strokeLinecap="round" opacity="0.45"/>
    <circle cx="16" cy="22" r="2.5" fill="#d4a053" opacity="0.2"/>
    <circle cx="72" cy="22" r="2" fill="#d4a053" opacity="0.2"/>
  </svg>,
];

function RandomIllustration({ seed }: { seed: string }) {
  const idx = hashStr(seed) % illustrationPool.length;
  return illustrationPool[idx];
}

// ── source type label ──────────────────────────────────────────────────────────

function sourceLabel(sourceType: string) {
  const map: Record<string, string> = {
    text: "文字",
    url: "网页",
    pdf: "PDF",
    document: "文档",
    image: "图片",
    manual: "手动",
  };
  return map[sourceType] ?? sourceType;
}

// ── time display ───────────────────────────────────────────────────────────

function relativeTime(value: string | null): string {
  if (!value) return "";
  const raw = /z|[+-]\d{2}:?\d{2}$/i.test(value) ? value : `${value}Z`;
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return "";
  const now = Date.now();
  const diff = now - d.getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} 天前`;
  return formatDateTime(value);
}

// ── Component ─────────────────────────────────────────────────────────────

export function MemoriesPage() {
  const [searchParams] = useSearchParams();
  const initialQ = searchParams.get("q") ?? "";

  const [searchInput, setSearchInput] = useState(initialQ);
  const [keyword, setKeyword] = useState(initialQ);
  const [category, setCategory] = useState("all");

  const query = useMemo(
    () => ({
      q: keyword || undefined,
      category: category === "all" ? undefined : category,
    }),
    [category, keyword],
  );

  const { data, isLoading, error } = useQuery({
    queryKey: ["memories", query],
    queryFn: () => api.listMemories(query),
  });

  function handleSearchSubmit(event: React.FormEvent) {
    event.preventDefault();
    setKeyword(searchInput.trim());
  }

  function clearSearch() {
    setSearchInput("");
    setKeyword("");
  }

  const hasFilter = Boolean(keyword) || category !== "all";

  return (
    <div className="mem-page">
      {/* Header */}
      <div className="mem-header">
        <div className="mem-header-left">
          <Brain size={20} className="mem-header-icon" />
          <div>
            <h1 className="mem-title">{"我的记录"}</h1>
            <p className="mem-subtitle">
              {"不用担心记得乱。你可以按主题筛一下，也可以直接搜一句大概记得的内容。"}
            </p>
          </div>
        </div>
        <span className="mem-count">{isLoading ? "…" : `共 ${data?.length ?? 0} 条`}</span>
      </div>

      {/* Search bar */}
      <form className="mem-search-bar" onSubmit={handleSearchSubmit}>
        <Search size={15} className="mem-search-icon" />
        <input
          className="mem-search-input"
          placeholder={"搜标题、摘要或原文，比如：pgvector、面试、周五"}
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
        />
        {searchInput && (
          <button
            type="button"
            className="mem-search-clear"
            onClick={clearSearch}
            aria-label={"清除搜索"}
          >
            <X size={14} />
          </button>
        )}
        <button className="mem-search-btn" type="submit">
          {"搜一下"}
        </button>
      </form>

      {/* Category chips */}
      <div className="mem-category-row" role="tablist" aria-label={"记录分类"}>
        {categoryOptions.map((opt) => (
          <button
            key={opt.value}
            type="button"
            role="tab"
            aria-selected={category === opt.value}
            className={`mem-cat-chip${category === opt.value ? " active" : ""}`}
            onClick={() => setCategory(opt.value)}
          >
            {opt.icon && <opt.icon size={13} />}
            {opt.label}
          </button>
        ))}
      </div>

      {/* Active filter notice */}
      {hasFilter && (
        <div className="mem-filter-notice">
          <span>
            {"当前筛选："}
            {category !== "all" && (
              <strong>{categoryOptions.find((o) => o.value === category)?.label}</strong>
            )}
            {keyword && category !== "all" && "，"}
            {keyword && <strong>"{keyword}"</strong>}
          </span>
          <button
            type="button"
            className="mem-filter-clear"
            onClick={() => { clearSearch(); setCategory("all"); }}
          >
            <X size={12} />
            {"清除筛选"}
          </button>
        </div>
      )}

      {/* Content */}
      {isLoading ? (
        <div className="mem-loading-list">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="mem-skeleton-card" />
          ))}
        </div>
      ) : error || !data ? (
        <div className="mem-error-state">
          {"记录列表加载失败，请稍后重试。"}
        </div>
      ) : data.length === 0 ? (
        <div className="mem-empty-state">
          <Brain size={32} />
          <p>
            {hasFilter
              ? "没有找到匹配的记录，换个关键词试试，或清除当前筛选。"
              : "还没有记录。先从一句生活小事开始，这里很快就会丰富起来。"}
          </p>
        </div>
      ) : (
        <div className="mem-list">
          {data.map((item) => (
            <Link
              key={item.id}
              to={`/app/memories/${item.id}`}
              className="mem-card"
            >
              {/* Illustration */}
              <div className="mem-card-illus-wrap" style={{ background: "linear-gradient(135deg, #f7f9f5 0%, #f0f5ee 100%)" }}>
                <RandomIllustration seed={item.id} />
              </div>

              {/* Body */}
              <div className="mem-card-body">
                <div className="mem-card-topline">
                  <span className="mem-card-cat" style={{ color: categoryColor(item.category) }}>
                    {formatCategory(item.category)}
                  </span>
                  <span className="mem-card-source">{sourceLabel(item.source_type)}</span>
                </div>

                <h3 className="mem-card-title">{item.title || "未命名记录"}</h3>

                {item.content_summary && (
                  <p className="mem-card-summary">{item.content_summary}</p>
                )}

                <div className="mem-card-bottom">
                  <div className="mem-card-tags">
                    {item.tags.slice(0, 3).map((tag) => (
                      <span key={tag} className="mem-tag">{tag}</span>
                    ))}
                    {item.tags.length > 3 && (
                      <span className="mem-tag mem-tag-more">+{item.tags.length - 3}</span>
                    )}
                  </div>
                </div>
              </div>

              {/* Right: status + time */}
              <div className="mem-card-right">
                <span className={`mem-status mem-status-${item.status}`}>
                  {formatMemoryStatus(item.status)}
                </span>
                <span className="mem-card-time">{relativeTime(item.event_time)}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
