"""
MemoryManager 集成测试

测试 MemoryManager 与真实数据库的集成:
1. EpisodicMemory 调用 memory_repository
2. SemanticMemory 调用 memory_repository
3. GoalMemory 调用 goal_repository
4. ProceduralMemory 调用 todo_repository, reminder_repository
5. InsightCache 调用 insight_repository
6. MemoryManager 上下文提供接口
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.memory.manager import MemoryManager
from app.models.memory import MemoryItem
from app.models.todo import TodoItem


# ============ EpisodicMemory 集成测试 ============


def test_episodic_memory_recent(db_session: Session, test_user_id: uuid.UUID):
    """测试获取最近记忆"""
    # 创建记忆数据
    m1 = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="记忆1", content_raw="内容1", category="note",
        tags=["标签1"], keywords=["关键词1"],
    )
    m2 = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="记忆2", content_raw="内容2", category="work",
        tags=["标签2"], keywords=["关键词2"],
    )
    db_session.add_all([m1, m2])
    db_session.commit()

    mm = MemoryManager(db_session, test_user_id)
    recent = mm.episodic.get_recent_memories(days=7, limit=10)

    assert len(recent) >= 2
    titles = {m["title"] for m in recent}
    assert "记忆1" in titles
    assert "记忆2" in titles


def test_episodic_memory_summary(db_session: Session, test_user_id: uuid.UUID):
    """测试情节记忆摘要"""
    m1 = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="记忆1", content_raw="内容1", category="note",
    )
    m2 = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="记忆2", content_raw="内容2", category="work",
    )
    db_session.add_all([m1, m2])
    db_session.commit()

    mm = MemoryManager(db_session, test_user_id)
    summary = mm.episodic.get_summary(days=30)

    assert summary["total_memories"] >= 2
    assert "date_range" in summary
    assert "category_breakdown" in summary


def test_episodic_memory_by_id(db_session: Session, test_user_id: uuid.UUID):
    """测试根据 ID 获取记忆"""
    m = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="记忆", content_raw="内容", category="note",
        tags=["tag1"], entities=["entity1"],
    )
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)

    mm = MemoryManager(db_session, test_user_id)
    result = mm.episodic.get_by_id(m.id)

    assert result is not None
    assert result["title"] == "记忆"
    assert "tag1" in result["tags"]

    # 不存在的
    assert mm.episodic.get_by_id(uuid.uuid4()) is None


# ============ SemanticMemory 集成测试 ============


def test_semantic_memory_profile(db_session: Session, test_user_id: uuid.UUID):
    """测试用户画像"""
    m1 = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="Python学习", content_raw="Python笔记", category="learning",
        tags=["编程", "Python"], keywords=["python", "学习"],
        entities=["Python"],
    )
    m2 = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="React项目", content_raw="React笔记", category="work",
        tags=["编程", "React"], keywords=["react", "前端"],
        entities=["React", "JavaScript"],
    )
    db_session.add_all([m1, m2])
    db_session.commit()

    mm = MemoryManager(db_session, test_user_id)
    profile = mm.semantic.get_user_profile()

    assert profile["total_memories"] >= 2
    assert "编程" in profile["interests"]
    assert "Python" in profile["frequent_entities"] or "React" in profile["frequent_entities"]


def test_semantic_memory_summary(db_session: Session, test_user_id: uuid.UUID):
    """测试语义记忆摘要"""
    m = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="测试", content_raw="内容", category="note",
        tags=["tag1", "tag2"], entities=["ent1"],
    )
    db_session.add(m)
    db_session.commit()

    mm = MemoryManager(db_session, test_user_id)
    summary = mm.semantic.get_summary()

    assert summary["total_memories"] >= 1
    assert summary["unique_tags"] >= 1
    assert "top_tags" in summary


def test_semantic_search_by_tag(db_session: Session, test_user_id: uuid.UUID):
    """测试按标签搜索"""
    m = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="Python笔记", content_raw="内容", category="learning",
        tags=["Python", "编程"],
    )
    db_session.add(m)
    db_session.commit()

    mm = MemoryManager(db_session, test_user_id)
    results = mm.semantic.search_by_tag("Python")

    assert len(results) >= 1
    assert results[0]["title"] == "Python笔记"


def test_semantic_search_by_entity(db_session: Session, test_user_id: uuid.UUID):
    """测试按实体搜索"""
    m = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="React项目", content_raw="内容", category="work",
        entities=["React", "TypeScript"],
    )
    db_session.add(m)
    db_session.commit()

    mm = MemoryManager(db_session, test_user_id)
    results = mm.semantic.search_by_entity("React")

    assert len(results) >= 1
    assert results[0]["title"] == "React项目"


# ============ GoalMemory 集成测试 ============


def test_goal_memory_create_and_list(db_session: Session, test_user_id: uuid.UUID):
    """测试创建和列出目标"""
    mm = MemoryManager(db_session, test_user_id)

    goal_id = mm.goal.create_goal("完成项目A", "这是一个重要项目", priority=5)
    assert goal_id is not None

    active = mm.goal.get_active_goals()
    assert len(active) == 1
    assert active[0]["title"] == "完成项目A"
    assert active[0]["priority"] == 5


def test_goal_memory_update(db_session: Session, test_user_id: uuid.UUID):
    """测试更新目标"""
    mm = MemoryManager(db_session, test_user_id)

    goal_id = mm.goal.create_goal("原始标题")
    updated = mm.goal.update_goal(goal_id, title="新标题", priority=10)

    assert updated is not None
    assert updated["title"] == "新标题"
    assert updated["priority"] == 10


def test_goal_memory_status_flow(db_session: Session, test_user_id: uuid.UUID):
    """测试目标状态流转"""
    mm = MemoryManager(db_session, test_user_id)

    goal_id = mm.goal.create_goal("测试目标")

    # active -> paused
    updated = mm.goal.update_goal(goal_id, status="paused")
    assert updated["status"] == "paused"

    # paused -> completed
    updated = mm.goal.update_goal(goal_id, status="completed")
    assert updated["status"] == "completed"

    # 活跃列表应该为空
    active = mm.goal.get_active_goals()
    assert len(active) == 0

    # 所有列表包含已完成的
    all_goals = mm.goal.get_all()
    assert len(all_goals) == 1


def test_goal_memory_link_memory(db_session: Session, test_user_id: uuid.UUID):
    """测试关联记忆到目标"""
    mm = MemoryManager(db_session, test_user_id)

    # 创建记忆
    m = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="记忆", content_raw="内容", category="note",
    )
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)

    # 创建目标并关联
    goal_id = mm.goal.create_goal("目标")
    link = mm.goal.link_memory_to_goal(m.id, goal_id, relevance_score=0.7)

    assert link["memory_id"] == str(m.id)
    assert link["goal_id"] == str(goal_id)
    assert link["relevance_score"] == 0.7

    # 查询目标关联的记忆
    memories = mm.goal.get_goal_memories(goal_id)
    assert len(memories) == 1

    # 查询记忆关联的目标
    goals = mm.goal.get_memory_goals(m.id)
    assert len(goals) == 1


def test_goal_memory_unlink(db_session: Session, test_user_id: uuid.UUID):
    """测试解除关联"""
    mm = MemoryManager(db_session, test_user_id)

    m = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="记忆", content_raw="内容", category="note",
    )
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)

    goal_id = mm.goal.create_goal("目标")
    mm.goal.link_memory_to_goal(m.id, goal_id)

    result = mm.goal.unlink_memory_from_goal(m.id, goal_id)
    assert result is True

    memories = mm.goal.get_goal_memories(goal_id)
    assert len(memories) == 0


# ============ ProceduralMemory 集成测试 ============


def test_procedural_memory_todos(db_session: Session, test_user_id: uuid.UUID):
    """测试获取待办"""
    t1 = TodoItem(
        user_id=test_user_id, title="待办1", status="pending", priority="high",
    )
    t2 = TodoItem(
        user_id=test_user_id, title="待办2", status="doing", priority="medium",
    )
    t3 = TodoItem(
        user_id=test_user_id, title="已完成", status="done", priority="low",
    )
    db_session.add_all([t1, t2, t3])
    db_session.commit()

    mm = MemoryManager(db_session, test_user_id)
    todos = mm.procedural.get_pending_todos(limit=10)

    # done的不应该出现
    assert len(todos) >= 2
    titles = {t["title"] for t in todos}
    assert "待办1" in titles
    assert "待办2" in titles
    assert "已完成" not in titles


# ============ InsightCache 集成测试 ============


def test_insight_cache_save_and_get(db_session: Session, test_user_id: uuid.UUID):
    """测试保存和获取洞察"""
    mm = MemoryManager(db_session, test_user_id)

    insight_id = mm.insights.save_insight(
        insight_type="pattern",
        title="每日模式",
        content="用户习惯在早上记录",
        data={"time": "08:00"},
        confidence_score=0.85,
    )
    assert insight_id is not None

    recent = mm.insights.get_recent(days=7)
    assert len(recent) == 1
    assert recent[0]["title"] == "每日模式"
    assert recent[0]["insight_type"] == "pattern"
    assert recent[0]["data"] == {"time": "08:00"}


def test_insight_cache_get_by_type(db_session: Session, test_user_id: uuid.UUID):
    """测试按类型获取洞察"""
    mm = MemoryManager(db_session, test_user_id)

    mm.insights.save_insight("pattern", "模式1", "内容", data={"key": "v1"})
    mm.insights.save_insight("pattern", "模式2", "内容", data={"key": "v2"})
    mm.insights.save_insight("report", "报告1", "内容")

    patterns = mm.insights.get_by_type("pattern")
    assert len(patterns) == 2

    reports = mm.insights.get_by_type("report")
    assert len(reports) == 1


def test_insight_cache_delete(db_session: Session, test_user_id: uuid.UUID):
    """测试删除洞察"""
    mm = MemoryManager(db_session, test_user_id)

    insight_id = mm.insights.save_insight("pattern", "待删除", "内容")
    assert mm.insights.delete_insight(insight_id) is True

    recent = mm.insights.get_recent(days=7)
    assert len(recent) == 0


def test_insight_cache_expiry(db_session: Session, test_user_id: uuid.UUID):
    """测试过期清理"""
    mm = MemoryManager(db_session, test_user_id)

    # 这个方法通过 insight_repo 处理，确保不报错
    deleted = mm.insights.cleanup_expired()
    assert deleted >= 0


# ============ MemoryManager 上下文接口测试 ============


def test_memory_manager_context_for_router(db_session: Session, test_user_id: uuid.UUID):
    """测试 Router 上下文"""
    mm = MemoryManager(db_session, test_user_id)

    # 添加工作记忆
    mm.working.add_turn("user", "测试消息")

    ctx = mm.get_context_for_router()

    assert "recent_conversation" in ctx
    assert "active_goals" in ctx
    assert "pending_todos" in ctx
    assert len(ctx["recent_conversation"]) == 1


def test_memory_manager_context_for_planner(db_session: Session, test_user_id: uuid.UUID):
    """测试 Planner 上下文"""
    mm = MemoryManager(db_session, test_user_id)

    ctx = mm.get_context_for_planner()

    assert "recent_conversation" in ctx
    assert "user_profile" in ctx
    assert "recent_insights" in ctx


def test_memory_manager_snapshot(db_session: Session, test_user_id: uuid.UUID):
    """测试完整快照"""
    mm = MemoryManager(db_session, test_user_id)

    mm.working.add_turn("user", "测试")
    mm.goal.create_goal("目标", "描述")

    snapshot = mm.snapshot()

    assert "working" in snapshot
    assert "goals" in snapshot
    assert "episodic_summary" in snapshot
    assert "semantic_summary" in snapshot
    assert len(snapshot["goals"]) == 1


def test_memory_manager_lazy_loading(db_session: Session, test_user_id: uuid.UUID):
    """测试延迟加载机制"""
    mm = MemoryManager(db_session, test_user_id)

    # 初始状态：所有层都未加载
    assert mm._working is None
    assert mm._episodic is None
    assert mm._semantic is None
    assert mm._goal is None
    assert mm._procedural is None
    assert mm._insights is None

    # 访问后加载
    _ = mm.working
    assert mm._working is not None

    _ = mm.goal
    assert mm._goal is not None

    # 其他层仍然未加载
    assert mm._semantic is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
