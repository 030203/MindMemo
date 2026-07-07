"""
RelationFinderTool 单元测试

测试覆盖:
  1. 有关联: 两条都有 "Python" 标签 → 返回关系
  2. 无关联: 完全不相关的记忆 → 空列表
  3. 排除自身: 不会把自己列为关联
  4. 多维混合: tags + keywords + entities + time 综合计分
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta

import pytest


def _make_memory(**overrides):
    from app.models.memory import MemoryItem

    defaults = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "source_type": "manual",
        "title": "测试记忆",
        "content_raw": "测试内容",
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


class TestRelationFinderCore:
    """核心关系发现测试"""

    def test_find_related_by_tags(self, db_session, test_user_id):
        """
        测试要点 1: 两条记忆共享 "Python" 标签 → 返回关系
        """
        from app.repos.memory_repo import memory_repository
        from app.tools.memory.relation_finder import RelationFinderTool

        src = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            title="Python闭包笔记",
            tags=["Python", "编程"],
            keywords=["闭包"],
        )
        rel = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            title="Python装饰器",
            tags=["Python", "设计模式"],
            keywords=["装饰器"],
        )
        # 无关
        other = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            title="周末菜单",
            tags=["生活", "美食"],
            keywords=["菜单"],
        )
        for m in [src, rel, other]:
            memory_repository.create(db_session, m)

        result = asyncio.run(
            RelationFinderTool().execute(
                memory_id=str(src.id),
                db=db_session,
                user_id=test_user_id,
            )
        )

        assert result.success is True
        # 应有至少 1 条关联，"Python" 标签匹配的那条
        assert len(result.data["relations"]) >= 1
        rel_ids = {r["target_memory_id"] for r in result.data["relations"]}
        assert str(rel.id) in rel_ids

    def test_no_relations(self, db_session, test_user_id):
        """
        测试要点 2: 完全不相关的记忆 → 空列表
        """
        from app.repos.memory_repo import memory_repository
        from app.tools.memory.relation_finder import RelationFinderTool

        src = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            title="独有笔记",
            tags=["独有标签"],
            keywords=["稀有词"],
            category="学习",
        )
        other = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            title="不相关",
            tags=["另一个标签"],
            keywords=["其他"],
            category="生活",
        )
        for m in [src, other]:
            memory_repository.create(db_session, m)
        # 手动错开创建时间，避免 time_bonus 误匹配
        db_session.flush()
        from datetime import timedelta
        other.created_at = src.created_at + timedelta(days=60)
        db_session.flush()

        result = asyncio.run(
            RelationFinderTool().execute(
                memory_id=str(src.id),
                db=db_session,
                user_id=test_user_id,
            )
        )

        assert result.success is True
        assert result.data["relations"] == []

    def test_exclude_self(self, db_session, test_user_id):
        """
        测试要点 3: 不会把自己列为关联
        """
        from app.repos.memory_repo import memory_repository
        from app.tools.memory.relation_finder import RelationFinderTool

        src = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            title="源记忆",
            tags=["Python"],
        )
        memory_repository.create(db_session, src)

        result = asyncio.run(
            RelationFinderTool().execute(
                memory_id=str(src.id),
                db=db_session,
                user_id=test_user_id,
            )
        )

        assert result.success is True
        rel_ids = {r["target_memory_id"] for r in result.data["relations"]}
        assert str(src.id) not in rel_ids

    def test_multidimensional_score(self, db_session, test_user_id):
        """
        测试要点 4: tags + keywords + entities + time + category 综合计分
        同一维度匹配越多，分数越高
        """
        from app.repos.memory_repo import memory_repository
        from app.tools.memory.relation_finder import RelationFinderTool

        now = datetime.now()
        src = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            title="源",
            tags=["Python", "编程"],
            keywords=["闭包", "函数"],
            entities=["lambda"],
            category="学习",
            event_time=now,
        )
        # 强关联：tags + keywords + entities + category + time 全匹配
        strong = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            title="强关联",
            tags=["Python", "编程"],
            keywords=["闭包", "作用域"],
            entities=["lambda"],
            category="学习",
            event_time=now + timedelta(minutes=30),
        )
        # 弱关联：仅 tags 匹配
        weak = _make_memory(
            id=uuid.uuid4(),
            user_id=test_user_id,
            title="弱关联",
            tags=["Python"],
            keywords=["其他"],
            category="生活",
        )
        for m in [src, strong, weak]:
            memory_repository.create(db_session, m)

        result = asyncio.run(
            RelationFinderTool().execute(
                memory_id=str(src.id),
                db=db_session,
                user_id=test_user_id,
            )
        )

        assert result.success is True
        scored = {r["target_memory_id"]: r["score"] for r in result.data["relations"]}
        assert scored[str(strong.id)] > scored.get(str(weak.id), 0), (
            f"强关联记忆分数应 > 弱关联: {scored}"
        )

    def test_invalid_uuid(self, db_session, test_user_id):
        """无效 UUID → success=False"""
        from app.tools.memory.relation_finder import RelationFinderTool

        result = asyncio.run(
            RelationFinderTool().execute(
                memory_id="not-a-uuid",
                db=db_session,
                user_id=test_user_id,
            )
        )
        assert result.success is False
        assert "UUID" in result.error

    def test_nonexistent_memory(self, db_session, test_user_id):
        """不存在的 memory_id → success=False"""
        from app.tools.memory.relation_finder import RelationFinderTool

        fake_id = uuid.uuid4()
        result = asyncio.run(
            RelationFinderTool().execute(
                memory_id=str(fake_id),
                db=db_session,
                user_id=test_user_id,
            )
        )
        assert result.success is False
        assert "不存在" in result.error


class TestRelationFinderRegistration:
    """工具注册 + Schema"""

    def test_register(self):
        from app.tools.registry import ToolRegistry
        from app.tools.memory.relation_finder import RelationFinderTool

        registry = ToolRegistry()
        registry.register(RelationFinderTool)
        tool = registry.get_tool("relation_finder")
        assert tool is not None

    def test_schema(self):
        from app.tools.memory.relation_finder import RelationFinderTool

        schema = RelationFinderTool().to_json_schema()
        assert schema["name"] == "relation_finder"
        assert "memory_id" in schema["parameters"]["required"]


class TestHelperFunctions:
    """辅助函数单元测试"""

    def test_field_overlap(self):
        from app.tools.memory.relation_finder import _field_overlap
        assert _field_overlap(["a", "b"], ["b", "c"]) == 1
        assert _field_overlap(["A"], ["a"]) == 1  # 大小写不敏感
        assert _field_overlap([], ["x"]) == 0

    def test_jaccard(self):
        from app.tools.memory.relation_finder import _jaccard
        assert _jaccard(["a", "b"], ["b", "c"]) == 1 / 3
        assert _jaccard([], []) == 0.0

    def test_time_bonus(self):
        from app.tools.memory.relation_finder import _time_bonus
        now = datetime.now()
        assert _time_bonus(now, now + timedelta(minutes=30)) > 0.15  # 30 分钟 → 高分
        assert _time_bonus(now, now + timedelta(days=7)) == 0.05   # 一周 → 低分
        assert _time_bonus(now, now + timedelta(days=30)) == 0.0   # 一个月 → 0
