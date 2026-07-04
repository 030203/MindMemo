"""
HybridSearchTool - 混合检索工具

职责：从用户记忆库中检索最相关内容，综合关键词匹配和标签/实体匹配。

============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  query: str          # 搜索查询
  top_k: int = 10     # 返回条数
  category: str = None # 可选类别过滤

[步骤2] 关键词提取
  从 query 中提取关键词 (简单分词/去停用词)
  例: "我上周学了什么Python库" → ["上周", "Python", "库"]

[步骤3] 双路检索
  [3.1] 关键词匹配 (memory_repository)
    调用 memory_repository.list_for_user(query_text=query, category=category)
    → 对 title/content_raw/content_summary 做 ILIKE 匹配

  [3.2] 标签/实体匹配 (SemanticMemory)
    将 query 分词后匹配语义层的 tags/keywords/entities
    → 取交集计分

[步骤4] 合并排序
  - 合并两路结果，按 relevance_score 降序
  - 去重: 同一 memory_id 只保留分数更高的
  - 截断 top_k

[步骤5] 返回 ToolResult
  ToolResult(
    success=True,
    data={
      "results": [{"memory_id", "title", "summary", "relevance", "source"}, ...],
      "total_matches": 25,
      "query": "我上周学了什么Python库"
    }
  )

============================================================
测试要点:
  1. 精确匹配: "Python" → 返回标题含 Python 的记忆
  2. 空结果: "火星基地" → 返回空列表, success=True
  3. 类别过滤: category="笔记" → 只返回笔记类型
  4. top_k 截断: top_k=3 → 最多返回 3 条
============================================================
"""
from __future__ import annotations

import re
import uuid
from collections import Counter

from sqlalchemy.orm import Session

from app.core.timeutil import local_isoformat
from app.tools.base import BaseTool, ToolResult, ToolParameter, ToolParameterType

# 分词策略：
# 1. 在CJK字符块前后插入空格 → "我学习了Python闭包" → " 我学习了  Python 闭包 "
# 2. 按空白字符和标点切分
# 3. 去停用词 + 去短词
_CJK_RE = re.compile(r"([一-鿿]+)")
_SPLIT_RE = re.compile(
    r"[\s,.;:!?，。；：！？、\"\'（）【】《》\-\+\/\\\[\]{}()@#$%^&*+=|~`]+"
)

# 无意义的停用词（检索时跳过）
_STOP_WORDS: set[str] = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
    "什么", "怎么", "如何", "哪个", "哪里", "吗", "呢", "啊", "吧", "哦",
    "what", "which", "who", "whom", "whose",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than",
    "too", "very", "just", "because", "but", "and", "or", "if", "while",
}


def _tokenize(text: str) -> list[str]:
    """分词 + 去停用词 + 去重（保持顺序）"""
    # 1. CJK字符前后加空格，方便后续按空白切分
    spaced = _CJK_RE.sub(r" \1 ", text)
    # 2. 按分隔符切分
    raw = _SPLIT_RE.split(spaced.lower())
    # 3. 去停用词 + 去短词 + 去重
    seen: set[str] = set()
    tokens: list[str] = []
    for t in raw:
        t = t.strip()
        if len(t) < 2:
            continue
        if t in _STOP_WORDS:
            continue
        if t not in seen:
            seen.add(t)
            tokens.append(t)
    return tokens


class HybridSearchTool(BaseTool):
    """
    混合检索工具 — 从用户记忆库查找相关内容

    检索策略：
    1. 关键词全文匹配：调 memory_repository 的 ILIKE 搜索(title/content_raw/content_summary)
    2. 语义标签匹配：将 query 分词后与每条记忆的 tags/keywords/entities 做交集

    合并时全文匹配权重更高(×2)，标签匹配作为补充，最终按分数排序取 top_k。
    """

    name: str = "hybrid_search"
    description: str = (
        "搜索用户记忆库中的相关内容。传入自然语言查询，返回按相关性排序的记忆列表，"
        "每条含标题、摘要和一段正文预览(content_preview)。"
        "适用于：查找用户之前记录的知识、笔记、想法；回答'我学过什么''我记录过什么'类问题。"
        "注意：结果只含正文预览片段；需要完整正文(如总结/分析整篇文章、简历)时，"
        "用返回的 memory_id 调 read_memory 获取全文。"
    )
    parameters: list[ToolParameter] = [
        ToolParameter(
            name="query",
            type=ToolParameterType.STRING,
            description="搜索查询，可以是自然语言问题或关键词",
            required=True,
        ),
        ToolParameter(
            name="top_k",
            type=ToolParameterType.INTEGER,
            description="返回结果的最大条数，默认 10",
            required=False,
            default=10,
        ),
        ToolParameter(
            name="category",
            type=ToolParameterType.STRING,
            description="按类别过滤，如'笔记'、'想法'、'待办'。不传则不限类别",
            required=False,
        ),
    ]

    # ------------------------------------------------------------------
    # 核心执行
    # ------------------------------------------------------------------

    async def execute(self, **kwargs) -> ToolResult:
        # [步骤1] 接收参数
        query: str = kwargs.get("query", "")
        top_k: int = kwargs.get("top_k", 10)
        category: str | None = kwargs.get("category")

        if not query or not query.strip():
            return ToolResult(success=False, error="query 不能为空")

        # 注意: 该工具需要数据库和用户上下文，期望通过注册时注入或调用时传入
        # 实际执行路径: Agent 通过 self._call_tool() 调用 → 工具实例已持有引用
        # 默认情况下，工具自身无状态 —— 检索需要 db 和 user_id 由 Agent 在调用前注入。
        # 此处假设 Agent 通过 tool_registry 获取工具实例后，将必要的上下文作为参数传递。
        #
        # 最终设计: execute() 通过 kwargs 接收除 query/top_k/category 之外的
        #   db: Session   — 数据会话 (由 Agent 注入)
        #   user_id: UUID — 用户 ID  (由 Agent 注入)
        db: Session | None = kwargs.get("db")
        user_id: uuid.UUID | None = kwargs.get("user_id")

        if db is None or user_id is None:
            return ToolResult(
                success=False,
                error="缺少 db 或 user_id 上下文 —— Agent 调用时需注入",
            )

        try:
            # [步骤2] 关键词提取
            tokens = _tokenize(query)

            # [步骤3] 双路检索
            # 3.1 关键词全文匹配 (memory_repository)
            from app.repos.memory_repo import memory_repository

            keyword_hits = memory_repository.list_for_user(
                db, user_id, query_text=query, category=category
            )
            # 3.2 标签/实体匹配 (对所有用户记忆扫描 tags/keywords/entities)
            all_memories = memory_repository.list_for_user(
                db, user_id, category=category
            )
            tag_scores: dict[uuid.UUID, int] = self._tag_match_scores(
                all_memories, tokens
            )

            # [步骤4] 合并排序
            scored: dict[uuid.UUID, dict] = {}  # memory_id → {item, relevance}

            # 关键词匹配: 基础分 = 1.0 (每条命中至少有一个字段匹配)
            for m in keyword_hits:
                extra = self._keyword_relevance(m, query, tokens)
                scored[m.id] = {"item": m, "relevance": 0.5 + extra, "source": "keyword"}

            # 标签匹配: 加分 (在 keyword 基础上叠加，或单独出现)
            for m in all_memories:
                tag_score = tag_scores.get(m.id, 0)
                if tag_score <= 0:
                    continue
                # 归一化: 最多 tokens 全匹配 → 0.4，base 0.2
                norm = 0.2 + 0.4 * min(tag_score / max(len(tokens), 1), 1.0)
                if m.id in scored:
                    scored[m.id]["relevance"] = min(
                        scored[m.id]["relevance"] + norm * 0.3, 1.0
                    )
                    scored[m.id]["source"] += "+tag"
                else:
                    scored[m.id] = {
                        "item": m,
                        "relevance": norm,
                        "source": "tag",
                    }

            # 排序 + 截断
            ranked = sorted(
                scored.values(), key=lambda x: x["relevance"], reverse=True
            )[:top_k]

            # [步骤5] 格式化结果
            results = []
            for entry in ranked:
                m = entry["item"]
                # 摘要缺失时用正文开头兜底；无论如何都带一段正文预览，
                # 让 Agent 搜索时就能看到真实内容，而不只是标题/标签。
                summary = m.content_summary or ""
                content_preview = self._content_preview(m)
                results.append({
                    "memory_id": str(m.id),
                    "title": m.title or "",
                    "summary": summary or content_preview,
                    "content_preview": content_preview,
                    "category": m.category,
                    "tags": m.tags or [],
                    "keywords": m.keywords or [],
                    "importance_score": m.importance_score,
                    "relevance": round(entry["relevance"], 4),
                    "source": entry["source"],
                    # 记录时刻(本地时间)——解读正文里"明天""下周"等相对时间的锚点
                    "recorded_at": local_isoformat(m.created_at),
                    "created_at": local_isoformat(m.created_at),
                })

            return ToolResult(
                success=True,
                data={
                    "results": results,
                    "total_matches": len(results),
                    "query": query,
                    "tokens": tokens,
                },
            )

        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _tag_match_scores(
        memories: list, tokens: list[str]
    ) -> dict[uuid.UUID, int]:
        """
        计算每条记忆的 tags/keywords/entities 与 query token 的重叠数。
        返回 {memory_id: overlap_count}。
        """
        scores: dict[uuid.UUID, int] = {}
        if not tokens:
            return scores
        token_set = set(tokens)
        for m in memories:
            match_count = 0
            for tag in m.tags or []:
                tag_lower = tag.lower()
                if tag_lower in token_set or any(
                    t in tag_lower for t in tokens
                ):
                    match_count += 1
            for kw in m.keywords or []:
                kw_lower = kw.lower()
                if kw_lower in token_set or any(
                    t in kw_lower for t in tokens
                ):
                    match_count += 1
            for ent in m.entities or []:
                ent_lower = str(ent).lower()
                if ent_lower in token_set or any(
                    t in ent_lower for t in tokens
                ):
                    match_count += 1
            if match_count > 0:
                scores[m.id] = match_count
        return scores

    @staticmethod
    def _keyword_relevance(m, query: str, tokens: list[str]) -> float:
        """
        计算单条记忆与查询的关键词匹配程度 (0~0.5 加成)。
        标题命中 > 摘要命中 > 正文命中。
        """
        bonus = 0.0
        q_lower = query.lower()
        title = (m.title or "").lower()
        summary = (m.content_summary or "").lower()

        # 标题完全包含 query → +0.3
        if q_lower in title:
            bonus += 0.3
        # 标题包含 >=1 个 token → +0.1/token (max 0.2)
        title_token_hits = sum(1 for t in tokens if t in title)
        bonus += min(title_token_hits * 0.1, 0.2)

        # 摘要完全包含 query → +0.2
        if q_lower in summary:
            bonus += 0.2
        # 摘要包含 >=1 个 token → +0.05/token (max 0.1)
        summary_token_hits = sum(1 for t in tokens if t in summary)
        bonus += min(summary_token_hits * 0.05, 0.1)

        return min(bonus, 0.5)

    # 正文预览长度：足够 Agent 判断相关性，又不至于灌爆上下文
    _PREVIEW_CHARS = 400

    @classmethod
    def _content_preview(cls, m) -> str:
        """取正文开头一段作为预览，去掉多余空白。完整正文需调 read_memory。"""
        raw = (getattr(m, "content_raw", "") or "").strip()
        if not raw:
            return ""
        preview = re.sub(r"\s+", " ", raw[: cls._PREVIEW_CHARS + 100]).strip()
        if len(preview) > cls._PREVIEW_CHARS:
            preview = preview[: cls._PREVIEW_CHARS].rstrip() + "…"
        return preview
