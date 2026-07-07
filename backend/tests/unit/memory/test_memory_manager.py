"""
MemoryManager和WorkingMemory单元测试

测试内容：
1. WorkingMemory基本功能
2. MemoryManager分层访问
3. 上下文提供接口
"""
import pytest
from uuid import uuid4
from app.memory.manager import MemoryManager
from app.memory.layers.working import WorkingMemory


# ============ WorkingMemory测试 ============

def test_working_memory_add_turn():
    """测试添加对话轮次"""
    wm = WorkingMemory(max_size=5)

    wm.add_turn("user", "你好")
    wm.add_turn("assistant", "你好，有什么可以帮助你的？")

    history = wm.get_all_turns()

    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


def test_working_memory_max_size():
    """测试最大容量限制"""
    wm = WorkingMemory(max_size=3)

    # 添加4轮对话
    for i in range(4):
        wm.add_turn("user", f"消息{i}")

    history = wm.get_all_turns()

    # 应该只保留最后3条
    assert len(history) == 3
    assert history[0]["content"] == "消息1"
    assert history[-1]["content"] == "消息3"


def test_working_memory_get_recent():
    """测试获取最近N轮"""
    wm = WorkingMemory()

    for i in range(5):
        wm.add_turn("user", f"消息{i}")

    recent = wm.get_recent_turns(n=2)

    assert len(recent) == 2
    assert recent[0]["content"] == "消息3"
    assert recent[1]["content"] == "消息4"


def test_working_memory_context():
    """测试上下文变量管理"""
    wm = WorkingMemory()

    # 设置
    wm.set_context("active_doc_id", "doc_123")
    wm.set_context("selected_text", "这是选中的文本")

    # 获取
    assert wm.get_context("active_doc_id") == "doc_123"
    assert wm.get_context("selected_text") == "这是选中的文本"
    assert wm.get_context("nonexistent", "default") == "default"

    # 移除
    removed = wm.remove_context("active_doc_id")
    assert removed is True
    assert wm.get_context("active_doc_id") is None


def test_working_memory_clear():
    """测试清空功能"""
    wm = WorkingMemory()

    wm.add_turn("user", "测试")
    wm.set_context("key", "value")

    # 清空上下文
    wm.clear_context()
    assert len(wm.current_context) == 0
    assert len(wm.get_all_turns()) == 1  # 对话历史不受影响

    # 清空对话历史
    wm.clear_history()
    assert len(wm.get_all_turns()) == 0


def test_working_memory_to_dict():
    """测试序列化"""
    wm = WorkingMemory(max_size=5)

    wm.add_turn("user", "你好")
    wm.set_context("key", "value")

    data = wm.to_dict()

    assert len(data["conversation_history"]) == 1
    assert data["current_context"]["key"] == "value"
    assert data["max_size"] == 5


def test_working_memory_repr():
    """测试字符串表示"""
    wm = WorkingMemory()

    wm.add_turn("user", "测试")
    wm.set_context("key", "value")

    repr_str = repr(wm)

    assert "WorkingMemory" in repr_str
    assert "turns=1" in repr_str
    assert "context_vars=1" in repr_str


# ============ MemoryManager测试 ============

def test_memory_manager_creation():
    """测试MemoryManager创建"""
    # 注意：这里使用None作为db，仅测试骨架
    # Phase 1实现时需要用真实的db_session
    mm = MemoryManager(db=None, user_id=uuid4())

    assert mm.db is None
    assert mm.user_id is not None


def test_memory_manager_working_lazy_init():
    """测试WorkingMemory延迟初始化"""
    mm = MemoryManager(db=None, user_id=uuid4())

    # 第一次访问时才创建
    assert mm._working is None

    working = mm.working
    assert working is not None
    assert isinstance(working, WorkingMemory)

    # 第二次访问返回同一个实例
    working2 = mm.working
    assert working is working2


def test_memory_manager_context_for_router():
    """测试为Router提供上下文"""
    mm = MemoryManager(db=None, user_id=uuid4())

    # 添加一些测试数据
    mm.working.add_turn("user", "测试消息")

    ctx = mm.get_context_for_router()

    assert "recent_conversation" in ctx
    assert "active_goals" in ctx
    assert "pending_todos" in ctx

    # WorkingMemory应该有数据
    assert len(ctx["recent_conversation"]) == 1


def test_memory_manager_context_for_planner():
    """测试为Planner提供上下文"""
    mm = MemoryManager(db=None, user_id=uuid4())

    ctx = mm.get_context_for_planner()

    assert "recent_conversation" in ctx
    assert "user_profile" in ctx
    assert "recent_insights" in ctx


def test_memory_manager_snapshot():
    """测试完整快照"""
    mm = MemoryManager(db=None, user_id=uuid4())

    mm.working.add_turn("user", "测试")

    snapshot = mm.snapshot()

    assert "working" in snapshot
    assert "goals" in snapshot
    assert "episodic_summary" in snapshot
    assert "semantic_summary" in snapshot


# ============ 集成测试 ============

def test_memory_manager_working_integration():
    """测试MemoryManager和WorkingMemory集成"""
    mm = MemoryManager(db=None, user_id=uuid4())

    # 通过MemoryManager访问WorkingMemory
    mm.working.add_turn("user", "第一条消息")
    mm.working.add_turn("assistant", "收到")
    mm.working.set_context("session_id", "test_123")

    # 验证数据
    ctx = mm.get_context_for_router()
    assert len(ctx["recent_conversation"]) == 2

    # 验证序列化
    snapshot = mm.snapshot()
    assert len(snapshot["working"]["conversation_history"]) == 2
    assert snapshot["working"]["current_context"]["session_id"] == "test_123"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
