"""
QA Agent 单元测试 (2.9)

测试要点:
  1. 正常提问 + LLM 可用 → status=success, answer 非空
  2. LLM 不可用 → status=unavailable, answer=兜底文案
  3. 带历史对话 → 历史被拼进 prompt
"""
from __future__ import annotations

from app.agent.qa_agent import QAAgent, QAResult


class TestQAAgent:
    def test_normal_answer(self):
        def fake_chat(system_prompt, user_prompt):
            return "今天天气晴朗。"

        result = QAAgent(llm_chat=fake_chat).answer("今天天气怎么样")
        assert result.status == "success"
        assert result.answer == "今天天气晴朗。"
        assert result.source == "qa_agent"

    def test_llm_unavailable(self):
        # llm_chat 返回 None → 不可用
        result = QAAgent(llm_chat=lambda system_prompt, user_prompt: None).answer("你好")
        assert result.status == "unavailable"
        assert "不可用" in result.answer

    def test_llm_empty_answer_unavailable(self):
        result = QAAgent(llm_chat=lambda system_prompt, user_prompt: "   ").answer("你好")
        assert result.status == "unavailable"

    def test_llm_raises_unavailable(self):
        def fake_chat(system_prompt, user_prompt):
            raise RuntimeError("network")

        result = QAAgent(llm_chat=fake_chat).answer("你好")
        assert result.status == "unavailable"

    def test_history_injected_into_prompt(self):
        captured = {}

        def fake_chat(system_prompt, user_prompt):
            captured["user_prompt"] = user_prompt
            return "好的"

        history = [
            {"role": "user", "content": "我在学 Python"},
            {"role": "assistant", "content": "不错，加油"},
        ]
        QAAgent(llm_chat=fake_chat).answer("接下来学什么", history=history)
        assert "我在学 Python" in captured["user_prompt"]
        assert "接下来学什么" in captured["user_prompt"]

    def test_no_history_prompt_is_question(self):
        captured = {}

        def fake_chat(system_prompt, user_prompt):
            captured["user_prompt"] = user_prompt
            return "答复"

        QAAgent(llm_chat=fake_chat).answer("你好")
        assert captured["user_prompt"] == "你好"

    def test_empty_question(self):
        # 空问题不应调用 LLM，直接给引导语
        called = {"v": False}

        def fake_chat(system_prompt, user_prompt):
            called["v"] = True
            return "x"

        result = QAAgent(llm_chat=fake_chat).answer("   ")
        assert result.status == "success"
        assert called["v"] is False


def test_qa_result_to_dict():
    d = QAResult(status="success", answer="hi").to_dict()
    assert d == {"status": "success", "answer": "hi", "source": "qa_agent"}
