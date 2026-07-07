"""
HybridSearchTool 单元测试

测试覆盖:
  1. 精确匹配: "Python" → 返回标题含 Python 的记忆
  2. 空结果: "火星基地" → 返回空列表, success=True
  3. 类别过滤: category="笔记" → 只返回笔记类型
  4. top_k 截断: top_k=3 → 最多返回 3 条
"""
from __future__ import annotations

import uuid

import pytest


def _make_memory(**overrides):
    """工厂函数: 创建 MemoryItem 实例 (用于测试数据准备)"""
    from app.models.memory import MemoryItem

    defaults = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "source_type": "manual",
        "title": "测试记忆",
        "content_raw": "测试内容",
        "content_clean": "测试内容",
        "content_summary": "测试摘要",
        "category": "笔记",
        "tags": [],
        "keywords": [],
        "entities": [],
        "time_info": {},
        "importance_score": 0.5,
        "status": "active",
    }
    defaults.update(overrides)
    return MemoryItem(**defaults)


class TestHybridSearchCore:
    """核心检索逻辑测试"""

    def test_exact_match_by_title(self, db_session, test_user_id):
        """
        测试要点 1: 精确匹配 — "Python" 应返回标题含 Python 的记忆
        """
        from app.repos.memory_repo import memory_repository
        from app.tools.retrieval.hybrid_search import HybridSearchTool

        # --- 准备数据 ---
        m1 = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            title="Python闭包学习笔记",
            content_raw="闭包是函数捕获了它定义时所在作用域的变量",
            content_summary="闭包概念",
            tags=["Python", "编程"],
            keywords=["闭包", "Python"],
            importance_score=0.9,
        )
        m2 = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            title="Java基础",
            content_raw="Java是一种面向对象语言",
            tags=["Java"],
            keywords=["Java"],
            importance_score=0.5,
        )
        memory_repository.create(db_session, m1)
        memory_repository.create(db_session, m2)

        tool = HybridSearchTool()

        # --- 执行 ---
        import asyncio

        result = asyncio.run(
            tool.execute(query="Python", db=db_session, user_id=test_user_id)
        )

        # --- 验证 ---
        assert result.success is True
        assert len(result.data["results"]) >= 1
        # "Python闭包学习笔记" 应在结果第一位
        titles = [r["title"] for r in result.data["results"]]
        assert any("Python" in t for t in titles), f"期望返回含Python的记忆，实际: {titles}"
        # Java 不应排第一
        if len(result.data["results"]) >= 2:
            top_title = result.data["results"][0]["title"]
            assert "Python" in top_title, f"Python记忆应排第一，实际: {top_title}"

    def test_empty_result(self, db_session, test_user_id):
        """
        测试要点 2: 空结果 — 查询无匹配时返回空列表且 success=True
        """
        from app.repos.memory_repo import memory_repository
        from app.tools.retrieval.hybrid_search import HybridSearchTool

        # --- 准备数据: 只有一条无关记忆 ---
        m = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            title="买菜清单",
            content_raw="西红柿、鸡蛋、牛奶",
            tags=["生活"],
        )
        memory_repository.create(db_session, m)

        tool = HybridSearchTool()

        # --- 执行 ---
        import asyncio

        result = asyncio.run(
            tool.execute(
                query="火星基地建设方案", db=db_session, user_id=test_user_id
            )
        )

        # --- 验证 ---
        assert result.success is True, f"空结果也应 success=True，实际: {result.error}"
        assert result.data["results"] == []

    def test_category_filter(self, db_session, test_user_id):
        """
        测试要点 3: 类别过滤 — category="学习" 只返回学习类记忆
        """
        from app.repos.memory_repo import memory_repository
        from app.tools.retrieval.hybrid_search import HybridSearchTool

        # --- 准备数据 ---
        m_study = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            title="FastAPI 路由学习",
            content_raw="路由装饰器用法",
            category="学习",
            tags=["FastAPI"],
        )
        m_life = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            title="周末购物",
            content_raw="超市采购",
            category="生活",
            tags=["购物"],
        )
        memory_repository.create(db_session, m_study)
        memory_repository.create(db_session, m_life)

        tool = HybridSearchTool()

        # --- 执行: 按"学习"类别过滤 ---
        import asyncio

        result = asyncio.run(
            tool.execute(query="路由", db=db_session, user_id=test_user_id, category="学习")
        )

        # --- 验证 ---
        assert result.success is True
        # 只应返回"学习"类
        categories = {r["category"] for r in result.data["results"]}
        assert categories == {"学习"}, f"期望只有学习类，实际: {categories}"

    def test_topk_truncation(self, db_session, test_user_id):
        """
        测试要点 4: top_k 截断 — top_k=2 时最多返回 2 条
        """
        from app.repos.memory_repo import memory_repository
        from app.tools.retrieval.hybrid_search import HybridSearchTool

        # --- 准备数据: 5 条 Python 相关 ---
        for i in range(5):
            m = _make_memory(
                id=uuid.uuid4(),
                user_id=test_user_id,
                title=f"Python笔记{i+1}",
                content_raw=f"Python 内容 {i+1}",
                tags=["Python"],
                importance_score=0.5 + i * 0.1,
            )
            memory_repository.create(db_session, m)

        tool = HybridSearchTool()

        # --- 执行: top_k=2 ---
        import asyncio

        result = asyncio.run(
            tool.execute(query="Python", db=db_session, user_id=test_user_id, top_k=2)
        )

        # --- 验证 ---
        assert result.success is True
        assert len(result.data["results"]) == 2, (
            f"期望最多 2 条，实际: {len(result.data['results'])}"
        )

    def test_no_db_context_returns_error(self):
        """
        边界条件: 不传 db/user_id → success=False
        """
        from app.tools.retrieval.hybrid_search import HybridSearchTool

        tool = HybridSearchTool()

        import asyncio

        result = asyncio.run(tool.execute(query="Python"))
        assert result.success is False
        assert "db" in result.error.lower() or "user_id" in result.error.lower()

    def test_empty_query_returns_error(self, db_session, test_user_id):
        """
        边界条件: 空 query → success=False
        """
        from app.tools.retrieval.hybrid_search import HybridSearchTool

        tool = HybridSearchTool()

        import asyncio

        result = asyncio.run(
            tool.execute(query="", db=db_session, user_id=test_user_id)
        )
        assert result.success is False
        assert "query" in result.error.lower()


class TestTagMatch:
    """标签匹配辅助函数测试"""

    def test_overlap_count(self):
        """token_set 与 tags/keywords 重叠计数"""
        from app.tools.retrieval.hybrid_search import HybridSearchTool

        m = _make_memory(
            tags=["Python", "闭包", "编程"],
            keywords=["函数", "作用域"],
            entities=["lambda"],
        )
        tokens = ["python", "闭包", "函数"]
        scores = HybridSearchTool._tag_match_scores([m], tokens)
        assert scores.get(m.id, 0) >= 3  # Python→tag, 闭包→tag, 函数→keyword

    def test_no_overlap(self):
        """无重叠 → 分数为0"""
        from app.tools.retrieval.hybrid_search import HybridSearchTool

        m = _make_memory(tags=["Java"], keywords=["OOP"])
        scores = HybridSearchTool._tag_match_scores([m], ["python", "闭包"])
        assert scores.get(m.id, 0) == 0


class TestHybridSearchRegistration:
    """工具注册 + Schema 导出测试"""

    def test_register_to_registry(self):
        """工具可注册到 ToolRegistry"""
        from app.tools.registry import ToolRegistry
        from app.tools.retrieval.hybrid_search import HybridSearchTool

        registry = ToolRegistry()
        registry.register(HybridSearchTool)

        tool = registry.get_tool("hybrid_search")
        assert tool is not None
        assert tool.name == "hybrid_search"
        assert "搜索用户记忆库" in tool.description

    def test_json_schema(self):
        """JSON Schema 符合 OpenAI Function Calling 规范"""
        from app.tools.retrieval.hybrid_search import HybridSearchTool

        tool = HybridSearchTool()
        schema = tool.to_json_schema()

        assert schema["name"] == "hybrid_search"
        assert "parameters" in schema
        assert "required" in schema["parameters"]
        assert "query" in schema["parameters"]["required"]
        # top_k 和 category 非必填
        assert "top_k" not in schema["parameters"]["required"]
        assert "category" not in schema["parameters"]["required"]


class TestTokenize:
    """分词辅助函数测试"""

    def test_chinese_basic(self):
        from app.tools.retrieval.hybrid_search import _tokenize

        tokens = _tokenize("我学习了Python闭包")
        # CJK_RE 切出 "我学习了" / "python" / "闭包"，停用词 "我" 在整词中不单独匹配
        assert "python" in tokens, f"tokens={tokens}"
        assert "闭包" in tokens, f"tokens={tokens}"

    def test_english_basic(self):
        from app.tools.retrieval.hybrid_search import _tokenize

        tokens = _tokenize("What is a closure in Python")
        assert "closure" in tokens, f"tokens={tokens}"
        assert "python" in tokens, f"tokens={tokens}"
        # "what" / "is" / "a" 都是停用词
        assert "what" not in tokens
        assert "is" not in tokens
        assert "a" not in tokens

    def test_short_tokens_filtered(self):
        from app.tools.retrieval.hybrid_search import _tokenize

        tokens = _tokenize("a b c Python 的 了")
        # 单字符+停用词全部滤掉
        for bad in ("a", "b", "c", "的", "了"):
            assert bad not in tokens
