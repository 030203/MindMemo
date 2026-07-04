"""
ListTasksTool - 待办/提醒查询工具

职责：从结构化的 todos 表查询用户的待办与提醒，并在**服务端**算好
      每条相对今天的时间状态（逾期/未来、还剩几天/逾期几天）。

为什么需要它：
  hybrid_search 只能在 memory 表里做模糊文本匹配，读到的是"7月10号之前交"
  这类原始文字，LLM 得自己心算日期——算不准、分不清逾期与未来。
  待办/提醒本就结构化存在 todos 表(due_at / remind_at / status)，
  本工具直接查库并做时间运算，LLM 只负责组织语言。

设计要点(对齐用户偏好):
  - 待办(纯待办, remind_at 为空)与提醒(remind_at 非空)分开
  - 待办按 deadline 是否已过分为 overdue / upcoming 两组
  - 提醒**只返回未来的**(remind_at >= 今天)，过去的提醒无意义
  - 每条自带 created_at(记录时间) / due_at(截止) / days_left(剩余,逾期为负)
  - 时区：DB 存 UTC，用 ensure_local 转本地后再和 localnow 比较，
    与 reminder_service 保持一致，避免"还剩几天"算错。

============================================================
返回 ToolResult.data 结构:
  {
    "today": "2026-07-04",
    "overdue_todos":  [<task>, ...],   # deadline 已过、未完成
    "upcoming_todos": [<task>, ...],   # 未来或无 deadline、未完成
    "upcoming_reminders": [<task>, ...],  # 未来的提醒
    "counts": {"overdue": n, "upcoming": n, "reminders": n}
  }
  <task> = {
    "todo_id", "title", "status", "priority",
    "created_at", "due_at", "remind_at",
    "days_left",      # 距 deadline 的天数(负=逾期)；无 deadline 为 None
    "time_state",     # "overdue" | "due_today" | "upcoming" | "no_deadline"
    "source_memory_id"
  }
============================================================
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.timeutil import ensure_local as _ensure_local, localnow as _localnow
from app.tools.base import BaseTool, ToolResult, ToolParameter, ToolParameterType


class ListTasksTool(BaseTool):
    """
    待办/提醒查询工具 — 查 todos 表并算好相对今天的时间状态。

    回答"我还有哪些待办/提醒""有什么快到期的"等问题时优先调用本工具，
    不要用 hybrid_search 猜测待办。
    """

    name: str = "list_tasks"
    description: str = (
        "查询用户的待办事项和提醒（来自结构化任务表，非记忆文本）。"
        "返回按时间状态分好组的任务：逾期待办、未来待办、未来提醒，"
        "每条都带记录时间、截止时间、以及距今还剩/逾期多少天（已在服务端算好）。"
        "回答'我还有哪些待办''还有什么提醒没做''有什么快到期的'时，"
        "优先用本工具，不要用 hybrid_search 猜测。"
    )
    parameters: list[ToolParameter] = [
        ToolParameter(
            name="include_done",
            type=ToolParameterType.BOOLEAN,
            description="是否包含已完成的任务，默认 False（只看未完成）",
            required=False,
            default=False,
        ),
    ]

    async def execute(self, **kwargs) -> ToolResult:
        db: Session | None = kwargs.get("db")
        user_id: uuid.UUID | None = kwargs.get("user_id")
        include_done: bool = bool(kwargs.get("include_done", False))

        if db is None or user_id is None:
            return ToolResult(
                success=False,
                error="缺少 db 或 user_id 上下文 —— Agent 调用时需注入",
            )

        try:
            from app.repos.todo_repo import todo_repository

            todos = todo_repository.list_for_user(db, user_id, sort="due")

            now = _localnow()
            today = now.date()

            overdue_todos: list[dict] = []
            upcoming_todos: list[dict] = []
            upcoming_reminders: list[dict] = []

            for todo in todos:
                if not include_done and todo.status == "done":
                    continue

                is_reminder = todo.remind_at is not None
                local_due = _ensure_local(todo.due_at)
                local_remind = _ensure_local(todo.remind_at)

                # 计算距 deadline 的天数（负=逾期），无 deadline 为 None
                days_left: int | None = None
                time_state = "no_deadline"
                if local_due is not None:
                    days_left = (local_due.date() - today).days
                    if days_left < 0:
                        time_state = "overdue"
                    elif days_left == 0:
                        time_state = "due_today"
                    else:
                        time_state = "upcoming"

                entry = self._to_entry(todo, days_left, time_state)

                if is_reminder:
                    # 提醒只保留未来的（含今天）；过去的提醒不返回
                    ref = local_remind or local_due
                    if ref is None or ref.date() >= today:
                        upcoming_reminders.append(entry)
                else:
                    if time_state == "overdue":
                        overdue_todos.append(entry)
                    else:
                        upcoming_todos.append(entry)

            # 逾期：越久越靠前；未来：越近越靠前
            overdue_todos.sort(key=lambda e: e["days_left"])
            upcoming_todos.sort(
                key=lambda e: (e["days_left"] is None, e["days_left"] if e["days_left"] is not None else 0)
            )
            upcoming_reminders.sort(
                key=lambda e: (e["remind_at"] is None, e["remind_at"] or "")
            )

            return ToolResult(
                success=True,
                data={
                    "today": today.isoformat(),
                    "overdue_todos": overdue_todos,
                    "upcoming_todos": upcoming_todos,
                    "upcoming_reminders": upcoming_reminders,
                    "counts": {
                        "overdue": len(overdue_todos),
                        "upcoming": len(upcoming_todos),
                        "reminders": len(upcoming_reminders),
                    },
                },
            )
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

    @staticmethod
    def _to_entry(todo, days_left: int | None, time_state: str) -> dict:
        local_created = _ensure_local(todo.created_at)
        local_due = _ensure_local(todo.due_at)
        local_remind = _ensure_local(todo.remind_at)
        return {
            "todo_id": str(todo.id),
            "title": todo.title,
            "status": todo.status,
            "priority": todo.priority,
            "created_at": local_created.isoformat() if local_created else None,
            "due_at": local_due.isoformat() if local_due else None,
            "remind_at": local_remind.isoformat() if local_remind else None,
            "days_left": days_left,
            "time_state": time_state,
            "source_memory_id": str(todo.source_memory_id) if todo.source_memory_id else None,
        }
