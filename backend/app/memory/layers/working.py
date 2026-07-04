"""
Working Memory - 工作记忆层

核心职责：
1. 管理当前会话的对话历史
2. 存储临时上下文变量
3. 为Agent提供短期记忆能力

特点：
- 纯内存存储，不持久化
- 有容量限制（默认保留最近10轮对话）
- 生命周期绑定到MemoryManager实例
"""
from collections import deque
from typing import Any, Optional


class WorkingMemory:
    """
    工作记忆 - 当前会话的短期上下文

    使用示例：
        wm = WorkingMemory(max_size=10)

        # 添加对话轮次
        wm.add_turn("user", "今天天气怎么样")
        wm.add_turn("assistant", "今天天气晴朗，温度25度")

        # 获取最近对话
        recent = wm.get_recent_turns(n=3)

        # 设置上下文变量
        wm.set_context("active_document_id", "doc_123")
        doc_id = wm.get_context("active_document_id")
    """

    def __init__(self, max_size: int = 10):
        """
        初始化工作记忆

        Args:
            max_size: 最大保留的对话轮次数
        """
        self.conversation_history: deque = deque(maxlen=max_size)
        self.current_context: dict[str, Any] = {}
        self.max_size = max_size

    def add_turn(self, role: str, content: str, metadata: Optional[dict] = None):
        """
        添加对话轮次

        Args:
            role: 角色（"user" 或 "assistant"）
            content: 对话内容
            metadata: 额外元数据（可选）
        """
        self.conversation_history.append({
            "role": role,
            "content": content,
            "metadata": metadata or {}
        })

    def get_recent_turns(self, n: int = 5) -> list[dict]:
        """
        获取最近n轮对话

        Args:
            n: 获取的轮次数

        Returns:
            对话列表，每项包含 role, content, metadata
        """
        return list(self.conversation_history)[-n:]

    def get_all_turns(self) -> list[dict]:
        """获取所有对话历史"""
        return list(self.conversation_history)

    def set_context(self, key: str, value: Any):
        """
        设置上下文变量

        Args:
            key: 变量名
            value: 变量值

        典型用途：
        - active_document_id: 当前查看的文档ID
        - selected_text: 用户选中的文本
        - active_memory_id: 当前操作的记忆ID
        """
        self.current_context[key] = value

    def get_context(self, key: str, default: Any = None) -> Any:
        """
        获取上下文变量

        Args:
            key: 变量名
            default: 默认值

        Returns:
            变量值，如果不存在返回default
        """
        return self.current_context.get(key, default)

    def remove_context(self, key: str) -> bool:
        """
        移除上下文变量

        Args:
            key: 变量名

        Returns:
            是否成功移除
        """
        if key in self.current_context:
            del self.current_context[key]
            return True
        return False

    def clear_context(self):
        """清空所有上下文变量"""
        self.current_context.clear()

    def clear_history(self):
        """清空对话历史"""
        self.conversation_history.clear()

    def to_dict(self) -> dict:
        """
        导出为字典（用于序列化）

        Returns:
            包含对话历史和上下文的字典
        """
        return {
            "conversation_history": list(self.conversation_history),
            "current_context": self.current_context,
            "max_size": self.max_size
        }

    def __repr__(self) -> str:
        return f"WorkingMemory(turns={len(self.conversation_history)}, context_vars={len(self.current_context)})"
