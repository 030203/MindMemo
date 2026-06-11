from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMAnswerResult:
    answer: str | None
    status: str
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.answer)


class LLMAnswerService:
    def is_available(self) -> bool:
        return bool(settings.openai_base_url and settings.openai_api_key)

    def generate_grounded_answer(
        self,
        *,
        question: str,
        provider: str,
        model: str,
        context_blocks: list[str],
        answer_mode: str = "grounded_qa",
    ) -> str | None:
        return self.generate_grounded_answer_result(
            question=question,
            provider=provider,
            model=model,
            context_blocks=context_blocks,
            answer_mode=answer_mode,
        ).answer

    def generate_grounded_answer_result(
        self,
        *,
        question: str,
        provider: str,
        model: str,
        context_blocks: list[str],
        answer_mode: str = "grounded_qa",
    ) -> LLMAnswerResult:
        if not context_blocks:
            return LLMAnswerResult(answer=None, status="skipped", reason="empty_context")

        if not self.is_available():
            return LLMAnswerResult(answer=None, status="unavailable", reason="missing_openai_config")

        system_prompt = self._system_prompt_for_mode(answer_mode)
        user_prompt = (
            f"用户问题：{question}\n\n"
            "可用记忆片段如下：\n"
            + "\n\n".join(context_blocks)
            + self._user_prompt_suffix_for_mode(answer_mode)
        )

        try:
            answer = self._chat_completion(
                provider=provider,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
            return LLMAnswerResult(answer=answer, status="ok")
        except Exception as exc:
            logger.warning("LLM grounded answer failed: %s", exc)
            return LLMAnswerResult(answer=None, status="error", reason=str(exc))

    def _chat_completion(
        self,
        *,
        provider: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        del provider

        base_url = (settings.openai_base_url or "").rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

        payload = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.35,
                "max_tokens": settings.llm_max_completion_tokens,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            url=f"{base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.openai_api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=settings.llm_request_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"LLM request failed: {exc.code} {detail}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("LLM response did not contain choices")

        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("LLM response content is empty")

        return content.strip()

    def _system_prompt_for_mode(self, answer_mode: str) -> str:
        base = (
            "你是 MindMemo 的个人记忆助手。"
            "你的输出必须受给定内容约束，不能编造片段里没有出现的事实。"
            "如果证据不足，要直接说明不确定。"
            "回答请使用自然、简洁、温和的中文。"
        )
        if answer_mode == "summarize":
            return base + "当前任务是总结全文。优先给出整体结论，再覆盖关键阶段、事件和结论。不要机械复述，也不要输出片段清单。"
        if answer_mode == "extract":
            return base + "当前任务是提取信息。请按用户要求穷尽提取，并保持原文顺序，避免遗漏。"
        if answer_mode == "transform":
            return base + "当前任务是内容改写或格式转换。请只基于当前全文输出转换结果，不要额外解释过程。"
        if answer_mode == "grounded_review":
            return base + "当前任务是结合整体理解和局部证据做分析。先给判断，再说明依据。"
        return (
            base
            + "当前任务是证据问答。优先直接回答问题，再补充 1 到 3 个重点。"
            + "允许做低风险解释性判断，但推断要用“可以看出”“更像是”“可能”等措辞标明。"
        )

    def _user_prompt_suffix_for_mode(self, answer_mode: str) -> str:
        if answer_mode == "summarize":
            return "\n\n请基于这些片段做完整总结，允许概括和归纳，但不要编造事实。"
        if answer_mode == "extract":
            return "\n\n请基于这些片段按要求提取信息，尽量完整，不要编造事实。"
        if answer_mode == "transform":
            return "\n\n请基于这些片段完成改写或格式转换，只输出结果，不要编造事实。"
        if answer_mode == "grounded_review":
            return "\n\n请基于这些片段先给出整体判断，再说明局部依据，不要编造事实。"
        return "\n\n请基于这些片段回答。允许总结和归纳，但不要编造片段里没有的事实。"


llm_answer_service = LLMAnswerService()
