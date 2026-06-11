import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import { api } from "../api/client";
import { describeImportance, formatCategory, formatDateTime, formatMemoryStatus } from "../utils/presentation";

const categoryOptions = [
  { value: "all", label: "全部" },
  { value: "memo", label: "随手记" },
  { value: "learning", label: "学习记录" },
  { value: "project", label: "项目进展" },
  { value: "idea", label: "灵感" },
];

export function MemoriesPage() {
  const [searchInput, setSearchInput] = useState("");
  const [keyword, setKeyword] = useState("");
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

  const selectedCategoryLabel = categoryOptions.find((item) => item.value === category)?.label ?? "全部";

  if (isLoading) {
    return <div className="loading">正在加载记录列表...</div>;
  }

  if (error || !data) {
    return <div className="error">记录列表加载失败。</div>;
  }

  const hasFilter = Boolean(keyword) || category !== "all";

  return (
    <div className="page-grid">
      <section className="panel">
        <div className="section-title">
          <h3>我的记录</h3>
          <span className="muted">共 {data.length} 条</span>
        </div>
        <p className="panel-subtitle">不用担心记得乱。你可以按主题筛一下，也可以直接搜一句你大概记得的内容。</p>

        <form className="memory-filter-bar" onSubmit={handleSearchSubmit}>
          <label className="search-box" htmlFor="memory-search">
            <Search size={16} />
            <input
              id="memory-search"
              className="search-input"
              placeholder="搜标题、摘要或原文，比如：pgvector、面试、周五"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </label>
          <button className="button-ghost" type="submit">
            搜一下
          </button>
        </form>

        <div className="capture-modes" role="tablist" aria-label="记录分类筛选">
          {categoryOptions.map((option) => (
            <button
              key={option.value}
              className={`mode-chip${category === option.value ? " active" : ""}`}
              type="button"
              onClick={() => setCategory(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>

        {hasFilter ? (
          <div className="soft-note memory-filter-note">
            当前筛选：{selectedCategoryLabel}
            {keyword ? `，关键词“${keyword}”` : ""}
          </div>
        ) : null}

        <div className="list">
          {data.length === 0 ? (
            <div className="empty-state">
              {hasFilter
                ? "这次筛选下还没有找到对应记录。可以换个关键词试试，或者切回全部看看。"
                : "你还没有记录。先从一句生活小事开始，这里很快就会丰富起来。"}
            </div>
          ) : (
            data.map((item) => (
              <Link className="list-item friendly-card" key={item.id} to={`/app/memories/${item.id}`}>
                <div className="list-item-header">
                  <div>
                    <strong>{item.title}</strong>
                    <p className="panel-subtitle">{item.content_summary}</p>
                  </div>
                  <span className="soft-tag">{formatCategory(item.category)}</span>
                </div>
                <div className="inline-meta">
                  <span>{describeImportance(item.importance_score)}</span>
                  <span>{formatMemoryStatus(item.status)}</span>
                  <span>{formatDateTime(item.event_time)}</span>
                </div>
                <div className="tag-row">
                  {item.tags.length === 0 ? (
                    <span className="tag">暂时还没有标签</span>
                  ) : (
                    item.tags.map((tag) => (
                      <span className="tag" key={`${item.id}-${tag}`}>
                        {tag}
                      </span>
                    ))
                  )}
                </div>
              </Link>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
