"""
GoalRepository 单元测试

测试内容:
1. 目标 CRUD 操作
2. 记忆-目标关联管理
3. 状态更新
4. 边界条件
"""
import uuid

import pytest
from sqlalchemy.orm import Session

from app.repos.goal_repo import goal_repository, GoalRepository


# ============ 目标 CRUD 测试 ============


def test_create_goal(db_session: Session, test_user_id: uuid.UUID):
    """测试创建目标"""
    goal = goal_repository.create(
        db_session,
        user_id=test_user_id,
        title="完成项目A",
        description="这是一个重要项目",
        priority=5,
    )

    assert goal.id is not None
    assert goal.title == "完成项目A"
    assert goal.description == "这是一个重要项目"
    assert goal.priority == 5
    assert goal.status == "active"
    assert goal.user_id == test_user_id


def test_get_by_id(db_session: Session, test_user_id: uuid.UUID):
    """测试根据 ID 获取目标"""
    goal = goal_repository.create(
        db_session, user_id=test_user_id, title="测试目标"
    )

    retrieved = goal_repository.get_by_id(db_session, goal.id, test_user_id)
    assert retrieved is not None
    assert retrieved.title == "测试目标"

    # 其他用户不应能访问
    other_user_id = uuid.uuid4()
    not_found = goal_repository.get_by_id(db_session, goal.id, other_user_id)
    assert not_found is None


def test_list_active(db_session: Session, test_user_id: uuid.UUID):
    """测试获取活跃目标"""
    # 创建2个活跃目标和1个暂停目标
    goal_repository.create(db_session, user_id=test_user_id, title="活跃1", priority=3)
    goal_repository.create(db_session, user_id=test_user_id, title="活跃2", priority=1)
    g3 = goal_repository.create(db_session, user_id=test_user_id, title="暂停", priority=0)
    goal_repository.update_status(db_session, g3.id, test_user_id, "paused")

    active = goal_repository.list_active(db_session, test_user_id)
    assert len(active) == 2
    # 高优先级排在前面
    assert active[0].title == "活跃1"
    assert active[1].title == "活跃2"


def test_list_all(db_session: Session, test_user_id: uuid.UUID):
    """测试获取所有目标"""
    goal_repository.create(db_session, user_id=test_user_id, title="目标1")
    goal_repository.create(db_session, user_id=test_user_id, title="目标2")
    g3 = goal_repository.create(db_session, user_id=test_user_id, title="目标3")
    goal_repository.update_status(db_session, g3.id, test_user_id, "completed")

    all_goals = goal_repository.list_all(db_session, test_user_id)
    assert len(all_goals) == 3
    # 包含不同状态的
    statuses = {g.status for g in all_goals}
    assert "active" in statuses
    assert "completed" in statuses


def test_update_status(db_session: Session, test_user_id: uuid.UUID):
    """测试更新目标状态"""
    goal = goal_repository.create(
        db_session, user_id=test_user_id, title="测试"
    )

    # 暂停
    updated = goal_repository.update_status(
        db_session, goal.id, test_user_id, "paused"
    )
    assert updated is not None
    assert updated.status == "paused"

    # 完成
    updated = goal_repository.update_status(
        db_session, goal.id, test_user_id, "completed"
    )
    assert updated.status == "completed"

    # 重新激活
    updated = goal_repository.update_status(
        db_session, goal.id, test_user_id, "active"
    )
    assert updated.status == "active"


def test_update_status_not_found(db_session: Session, test_user_id: uuid.UUID):
    """测试更新不存在目标的返回"""
    result = goal_repository.update_status(
        db_session, uuid.uuid4(), test_user_id, "active"
    )
    assert result is None


def test_update_goal(db_session: Session, test_user_id: uuid.UUID):
    """测试更新目标信息"""
    goal = goal_repository.create(
        db_session, user_id=test_user_id, title="原始标题", priority=1
    )

    updated = goal_repository.update(
        db_session,
        goal.id,
        test_user_id,
        title="新标题",
        description="新描述",
        priority=10,
    )
    assert updated is not None
    assert updated.title == "新标题"
    assert updated.description == "新描述"
    assert updated.priority == 10


def test_update_goal_partial(db_session: Session, test_user_id: uuid.UUID):
    """测试部分更新目标"""
    goal = goal_repository.create(
        db_session, user_id=test_user_id, title="标题", description="描述"
    )

    # 只更新标题
    updated = goal_repository.update(
        db_session, goal.id, test_user_id, title="新标题"
    )
    assert updated.title == "新标题"
    assert updated.description == "描述"  # 不变


# ============ 记忆-目标关联测试 ============


def test_link_memory_to_goal(db_session: Session, test_user_id: uuid.UUID):
    """测试关联记忆到目标"""
    from app.models.memory import MemoryItem

    # 创建记忆
    memory = MemoryItem(
        user_id=test_user_id,
        source_type="manual",
        title="测试记忆",
        content_raw="这是一条测试记忆",
        category="note",
    )
    db_session.add(memory)
    db_session.commit()
    db_session.refresh(memory)

    # 创建目标
    goal = goal_repository.create(
        db_session, user_id=test_user_id, title="测试目标"
    )

    # 关联
    link = goal_repository.link_memory(
        db_session, goal.id, memory.id, relevance_score=0.8
    )
    assert link is not None
    assert link.memory_id == memory.id
    assert link.goal_id == goal.id
    assert link.relevance_score == 0.8


def test_link_memory_idempotent(db_session: Session, test_user_id: uuid.UUID):
    """测试重复关联是幂等的 (更新评分)"""
    from app.models.memory import MemoryItem

    memory = MemoryItem(
        user_id=test_user_id,
        source_type="manual",
        title="测试记忆",
        content_raw="内容",
        category="note",
    )
    db_session.add(memory)
    db_session.commit()
    db_session.refresh(memory)

    goal = goal_repository.create(
        db_session, user_id=test_user_id, title="测试目标"
    )

    # 第一次关联
    link1 = goal_repository.link_memory(
        db_session, goal.id, memory.id, relevance_score=0.5
    )
    # 第二次关联 (更新评分)
    link2 = goal_repository.link_memory(
        db_session, goal.id, memory.id, relevance_score=0.9
    )

    assert link1.id == link2.id
    assert link2.relevance_score == 0.9

    # 数据库里只有一条记录
    links = goal_repository.get_linked_memories(
        db_session, goal.id, test_user_id
    )
    assert len(links) == 1


def test_unlink_memory(db_session: Session, test_user_id: uuid.UUID):
    """测试解除记忆-目标关联"""
    from app.models.memory import MemoryItem

    memory = MemoryItem(
        user_id=test_user_id,
        source_type="manual",
        title="测试记忆",
        content_raw="内容",
        category="note",
    )
    db_session.add(memory)
    db_session.commit()
    db_session.refresh(memory)

    goal = goal_repository.create(
        db_session, user_id=test_user_id, title="测试目标"
    )
    goal_repository.link_memory(db_session, goal.id, memory.id)

    # 解除关联
    result = goal_repository.unlink_memory(db_session, goal.id, memory.id)
    assert result is True

    # 确认已解除
    links = goal_repository.get_linked_memories(
        db_session, goal.id, test_user_id
    )
    assert len(links) == 0


def test_unlink_memory_not_found(db_session: Session):
    """测试解除不存在的关联"""
    result = goal_repository.unlink_memory(
        db_session, uuid.uuid4(), uuid.uuid4()
    )
    assert result is False


def test_get_linked_memories(db_session: Session, test_user_id: uuid.UUID):
    """测试获取目标关联的所有记忆"""
    from app.models.memory import MemoryItem

    m1 = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="记忆1", content_raw="内容1", category="note",
    )
    m2 = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="记忆2", content_raw="内容2", category="note",
    )
    db_session.add_all([m1, m2])
    db_session.commit()
    db_session.refresh(m1)
    db_session.refresh(m2)

    goal = goal_repository.create(
        db_session, user_id=test_user_id, title="目标"
    )
    goal_repository.link_memory(db_session, goal.id, m1.id, relevance_score=0.9)
    goal_repository.link_memory(db_session, goal.id, m2.id, relevance_score=0.3)

    links = goal_repository.get_linked_memories(
        db_session, goal.id, test_user_id
    )
    assert len(links) == 2
    # 按评分降序排列
    assert links[0].relevance_score == 0.9
    assert links[1].relevance_score == 0.3


def test_get_linked_goals(db_session: Session, test_user_id: uuid.UUID):
    """测试获取记忆关联的所有目标"""
    from app.models.memory import MemoryItem

    memory = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="记忆", content_raw="内容", category="note",
    )
    db_session.add(memory)
    db_session.commit()
    db_session.refresh(memory)

    g1 = goal_repository.create(
        db_session, user_id=test_user_id, title="目标1"
    )
    g2 = goal_repository.create(
        db_session, user_id=test_user_id, title="目标2"
    )
    goal_repository.link_memory(db_session, g1.id, memory.id)
    goal_repository.link_memory(db_session, g2.id, memory.id)

    links = goal_repository.get_linked_goals(db_session, memory.id)
    assert len(links) == 2


def test_link_memory_user_isolation(db_session: Session, test_user_id: uuid.UUID):
    """测试 get_linked_memories 的用户隔离"""
    from app.models.memory import MemoryItem

    memory = MemoryItem(
        user_id=test_user_id, source_type="manual",
        title="记忆", content_raw="内容", category="note",
    )
    db_session.add(memory)
    db_session.commit()
    db_session.refresh(memory)

    goal = goal_repository.create(
        db_session, user_id=test_user_id, title="目标"
    )
    goal_repository.link_memory(db_session, goal.id, memory.id)

    # 其他用户查询同一目标应该为空
    other_user_id = uuid.uuid4()
    links = goal_repository.get_linked_memories(
        db_session, goal.id, other_user_id
    )
    assert len(links) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
