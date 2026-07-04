"""
Mailbox - Agent 间通信信箱

职责：为 Multi-Agent 提供解耦通信机制。
  Coordinator 把任务写进子 Agent 的 inbox，子 Agent 执行完把结果写回 Coordinator。

设计原则：
  - 进程内共享（本阶段不跨进程，asyncio 安全）
  - Coordinator 和子 Agent 通过 agent_id 寻址
  - 每个子 Agent 有自己的 inbox（任务）和 outbox（结果）
  - 子 Agent 上限由 Mailbox.count_sub_agents() 控制，CreateSubAgentTool 检查
============================================================
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Message:
    """Mailbox 中传递的消息"""
    msg_id: str
    from_agent: str
    to_agent: str
    type: str          # "task" | "result"
    task_id: str
    content: dict      # type=task 时: {question, context, allowed_tools}
                       # type=result 时: {answer, sources, status, error?}

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "from": self.from_agent,
            "to": self.to_agent,
            "type": self.type,
            "task_id": self.task_id,
            "content": self.content,
        }


class MailboxSlot:
    """单个 Agent 的信箱槽位"""
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.inbox: list[Message] = []
        self.outbox: list[Message] = []

    def push(self, msg: Message):
        self.inbox.append(msg)

    def pop_task(self) -> Message | None:
        """取出第一个 task 类型的消息"""
        for i, m in enumerate(self.inbox):
            if m.type == "task":
                self.inbox.pop(i)
                return m
        return None

    def add_result(self, msg: Message):
        self.outbox.append(msg)

    def clear(self):
        self.inbox.clear()
        self.outbox.clear()


class Mailbox:
    """
    信箱 - 进程内 Agent 通信

    用法:
        mailbox = Mailbox()
        coord_id = mailbox.create_slot("coordinator")
        sub_id = mailbox.create_slot("sub_t1")
        mailbox.send(coord_id, sub_id, Message(type="task", ...))
        task_msg = mailbox.read_inbox(sub_id)  # 取出任务
        mailbox.send(sub_id, coord_id, Message(type="result", ...))
        result_msgs = mailbox.get_results_for(coord_id)
    """

    COORDINATOR_ID = "coordinator"

    def __init__(self, max_sub_agents: int = 3):
        self._slots: dict[str, MailboxSlot] = {}
        self._max_sub_agents = max_sub_agents

    def create_slot(self, agent_id: str | None = None) -> str:
        """创建一个信箱槽位，返回 agent_id。agent_id 不传则自动生成。"""
        if agent_id is None:
            agent_id = f"agent_{uuid.uuid4().hex[:8]}"
        if agent_id in self._slots:
            raise ValueError(f"agent_id '{agent_id}' 已存在")
        self._slots[agent_id] = MailboxSlot(agent_id)
        return agent_id

    def send(self, from_agent: str, to_agent: str, msg: Message):
        """发送消息到目标 Agent 的信箱。"""
        if to_agent not in self._slots:
            raise ValueError(f"agent '{to_agent}' 不存在")
        self._slots[to_agent].push(msg)

    def read_inbox(self, agent_id: str) -> list[Message]:
        """读取 inbox 中所有消息（不移除）。"""
        slot = self._slots.get(agent_id)
        if slot is None:
            return []
        return list(slot.inbox)

    def pop_task(self, agent_id: str) -> Message | None:
        """取出第一个 task 类型消息（取出后从 inbox 移除）。"""
        slot = self._slots.get(agent_id)
        if slot is None:
            return None
        return slot.pop_task()

    def submit_result(self, agent_id: str, msg: Message):
        """子 Agent 提交结果（写入自己的 outbox + Coordinator 的 inbox）。"""
        if agent_id not in self._slots:
            raise ValueError(f"agent '{agent_id}' 不存在")
        self._slots[agent_id].add_result(msg)
        self.send(agent_id, self.COORDINATOR_ID, msg)

    def get_results_for(self, agent_id: str) -> list[Message]:
        """获取发往该 Agent 的 result 消息。"""
        slot = self._slots.get(agent_id)
        if slot is None:
            return []
        return [m for m in slot.inbox if m.type == "result"]

    def clear_results_for(self, agent_id: str):
        """清除该 Agent 的 result 消息（单次 collect 后清理）。"""
        slot = self._slots.get(agent_id)
        if slot is None:
            return
        slot.inbox = [m for m in slot.inbox if m.type != "result"]

    def count_sub_agents(self) -> int:
        """当前子 Agent 数量（排除 coordinator）。"""
        return sum(1 for aid in list(self._slots.keys())
                   if aid != self.COORDINATOR_ID)

    def max_sub_agents(self) -> int:
        return self._max_sub_agents

    def clear(self):
        self._slots.clear()
