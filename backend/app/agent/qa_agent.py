"""
QA Agent - 单轮问答 Agent (Fast 链路终点)

职责：处理 Router 判定为 fast 的请求，单轮生成自然语言回复。
  - 不做多步 ReAct，不强制调用工具
  - 可选注入 working memory 的最近对话，做轻量上下文衔接

============================================================
内部处理流程:
============================================================

[步骤1] 接收输入
  question: str            # 用户问题
  history: list[dict]      # 最近对话(可选) [{role, content}, ...]

[步骤2] 组装 messages
  system: MindMemo 助手人设
  + 历史对话(若有)
  + 当前 question

[步骤3] 调 LLM 生成回复
  走 llm_answer_service（urllib 实现，已验证可用）
  LLM 不可用 → 返回兜底文案，status=unavailable

[步骤4] 返回结构化结果
  {status, answer, source}

============================================================
测试要点:
  1. 正常提问 + LLM 可用 → status=success, answer 非空
  2. LLM 不可用 → status=unavailable, answer=兜底文案
  3. 带历史对话 → 历史被拼进 prompt
============================================================
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


_SYSTEM_PROMPT = (
    "你是 MindMemo 的个人记忆助手。"
    "请用自然、简洁、温和的中文回答用户的问题。"
    "如果不知道答案，请诚实地说不知道。"
)

_FALLBACK_ANSWER = "抱歉，AI 服务当前不可用。请检查 API Key 配置。"


@dataclass
class QAResult:
    status: str          # "success" | "unavailable"
    answer: str
    source: str = "qa_agent"

    def to_dict(self) -> dict:
        return {"status": self.status, "answer": self.answer, "source": self.source}


class QAAgent:
    """
    单轮问答 Agent

    用法：
        agent = QAAgent()
        result = agent.answer("你好")

    为便于测试，LLM 调用通过 `llm_chat` 注入：
        agent = QAAgent(llm_chat=fake_fn)
    fake_fn 签名: (system_prompt: str, user_prompt: str) -> str | None
    """

    def __init__(self, llm_chat: Optional[Callable[..., Optional[str]]] = None):
        self._llm_chat = llm_chat

    def answer(self, question: str, history: Optional[list[dict]] = None) -> QAResult:
        # [步骤1] 接收输入
        q = (question or "").strip()
        if not q:
            return QAResult(status="success", answer="请问有什么可以帮你的？")

        # [步骤2] 组装 user prompt（把历史拼进去做轻量上下文衔接）
        user_prompt = self._build_prompt(q, history or [])

        # [步骤3] 调 LLM
        chat = self._get_chat()
        if chat is None:
            return QAResult(status="unavailable", answer=_FALLBACK_ANSWER)

        try:
            answer = chat(system_prompt=_SYSTEM_PROMPT, user_prompt=user_prompt)
        except Exception:
            answer = None

        # [步骤4] 返回
        if not answer or not str(answer).strip():
            return QAResult(status="unavailable", answer=_FALLBACK_ANSWER)
        return QAResult(status="success", answer=str(answer).strip())

    def _build_prompt(self, question: str, history: list[dict]) -> str:
        if not history:
            return question
        lines = ["以下是最近的对话历史，供你理解上下文："]
        for turn in history:
            role = "用户" if turn.get("role") == "user" else "助手"
            content = (turn.get("content") or "").strip()
            if content:
                lines.append(f"{role}：{content}")
        lines.append(f"\n当前问题：{question}")
        return "\n".join(lines)

    def _get_chat(self) -> Optional[Callable[..., Optional[str]]]:
        if self._llm_chat is not None:
            return self._llm_chat
        from app.services.llm_answer_service import llm_answer_service
        if not llm_answer_service.is_available():
            return None
        return llm_answer_service.chat_with_system
