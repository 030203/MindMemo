from __future__ import annotations

import itertools
import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

from app.core.config import settings

_DBG_LOG = Path(__file__).resolve().parents[3] / "debug-c9d69d.log"
_dbg_content_logged = False


def _agent_dbg(location: str, message: str, data: dict, hypothesis_id: str) -> None:
    # #region agent log
    try:
        with _DBG_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "sessionId": "c9d69d",
                "location": location,
                "message": message,
                "data": data,
                "hypothesisId": hypothesis_id,
                "timestamp": int(time.time() * 1000),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # #endregion

logger = logging.getLogger(__name__)

# 小米多 key 轮询计数器（线程安全）
_xiaomi_key_lock = threading.Lock()
_xiaomi_key_cycle: "itertools.cycle | None" = None


def _next_xiaomi_key() -> str | None:
    """从 settings.xiaomi_key_list 轮询取下一个 key（线程安全）。"""
    global _xiaomi_key_cycle
    keys = settings.xiaomi_key_list
    if not keys:
        return None
    with _xiaomi_key_lock:
        if _xiaomi_key_cycle is None:
            _xiaomi_key_cycle = itertools.cycle(keys)
        return next(_xiaomi_key_cycle)


@dataclass(frozen=True)
class LLMAnswerResult:
    answer: str | None
    status: str
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return bool(self.answer)


class LLMAnswerService:
    def _active_provider(self) -> str:
        return (settings.llm_provider or "deepseek").strip().lower()

    def _active_user_facing_provider(self) -> str:
        """用户可见回答的 provider，未设置时回退到 llm_provider。"""
        if settings.llm_user_facing_provider and settings.llm_user_facing_provider.strip():
            return settings.llm_user_facing_provider.strip().lower()
        return self._active_provider()

    def is_available(self) -> bool:
        """检查至少有一个 provider 可用。"""
        has_deepseek = bool(settings.openai_base_url and settings.openai_api_key)
        has_xiaomi = bool(settings.xiaomi_base_url and settings.xiaomi_key_list)
        return has_deepseek or has_xiaomi

    def _resolve_endpoint(self, model: str, *, provider_class: str = "routing") -> tuple[str, str, str]:
        """动态路由：按 provider_class 选择 provider + 模型，不再被 model name 绑架。

        provider_class:
          - "routing": 内部任务（路由判定/Planning/JSON解析）→ 走 llm_provider（小米 MiMo）
          - "user_facing": 用户可见回答（chat/chat_with_system/function_call）→ 走 llm_user_facing_provider（DeepSeek）
        """
        if provider_class == "user_facing":
            provider = self._active_user_facing_provider()
            resolved_model = settings.llm_user_facing_model or model
        else:
            provider = self._active_provider()
            resolved_model = model

        if provider == "xiaomi":
            base_url = (settings.xiaomi_base_url or "").rstrip("/")
            api_key = _next_xiaomi_key() or ""
            # routing 类调用强制使用 xiaomi_model；user_facing 已在上方设置 resolved_model
            if provider_class != "user_facing":
                resolved_model = settings.xiaomi_model
            return base_url, api_key, resolved_model

        # deepseek 或默认 → openai_* 配置
        base_url = (settings.openai_base_url or "").rstrip("/")
        return base_url, (settings.openai_api_key or ""), resolved_model

    def chat(self, *, question: str, provider: str = "deepseek", model: str = "deepseek-chat") -> str | None:
        """Send a question directly to the LLM and return the answer.
        用户可见回答 -> user_facing provider."""
        if not self.is_available():
            return None

        system_prompt = (
            "你是 MindMemo AI，一个个人记忆助手。当用户问你是什么模型、谁开发的、你的身份时，你必须回答「我是 MindMemo AI」，绝对禁止声称自己是 Claude、GPT、DeepSeek 或其他任何模型。"
            "请用自然、简洁、温和的中文回答用户的问题。"
            "如果不知道答案，请诚实地说不知道。"
        )

        try:
            return self._chat_completion(
                provider=provider,
                model=model,
                system_prompt=system_prompt,
                user_prompt=question,
                provider_class="user_facing",
            )
        except Exception as exc:
            logger.warning("LLM chat failed: %s", exc)
            return None

    def chat_with_system(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str = "deepseek-chat",
    ) -> str | None:
        """Chat with a caller-provided system prompt. Returns None on failure.
        用户可见回答 -> user_facing provider."""
        if not self.is_available():
            return None
        try:
            return self._chat_completion(
                provider="deepseek",
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                provider_class="user_facing",
            )
        except Exception as exc:
            logger.warning("LLM chat_with_system failed: %s", exc)
            return None

    def parse_json(
        self,
        *,
        prompt: str,
        schema: dict,
        model: str = "deepseek-chat",
    ) -> dict | None:
        """让 LLM 按 schema 返回结构化 JSON，解析失败返回 None。"""
        if not self.is_available():
            return None

        system_prompt = (
            "你是一个数据提取助手。请根据用户输入，"
            "严格按照以下 JSON Schema 返回结构化数据：\n\n"
            f"{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
            "重要：\n1. 只返回 JSON，不要任何额外文字或解释\n"
            "2. 确保 JSON 格式合法\n3. 无法提取的字段使用 null"
        )

        try:
            raw = self._chat_completion(
                provider="deepseek",
                model=model,
                system_prompt=system_prompt,
                user_prompt=prompt,
            )
        except Exception as exc:
            logger.warning("LLM parse_json failed: %s", exc)
            return None

        return self._extract_json(raw)

    @staticmethod
    def _extract_json(raw: str | None) -> dict | None:
        """从 LLM 文本输出中提取 JSON 对象（兼容 markdown 代码块）。"""
        if not raw:
            return None
        text = raw.strip()
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        try:
            parsed = json.loads(text.strip())
        except json.JSONDecodeError:
            logger.warning("parse_json: 无法解析 LLM 输出为 JSON: %s", text[:200])
            return None
        return parsed if isinstance(parsed, dict) else None

    def function_call(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        model: str = "deepseek-chat",
    ) -> dict | None:
        """
        调用 LLM 的 function calling / tool use 能力。

        Args:
            messages: 对话消息列表 [{"role": str, "content": str}, ...]
            tools: 工具 schema 列表（OpenAI function calling 格式）
            model: 模型名

        Returns:
            {"type": "tool_call", "name": str, "arguments": dict}
            {"type": "text", "content": str}
            None（LLM 不可用）
        """
        if not self.is_available():
            return None

        try:
            data = self._chat_completion_raw(
                messages=messages, tools=tools, provider_class="user_facing",
            )
        except Exception as exc:
            logger.warning("LLM function_call failed: %s", exc)
            return None

        choices = data.get("choices") or []
        if not choices:
            return None

        msg = choices[0].get("message") or {}
        finish_reason = choices[0].get("finish_reason", "")

        # LLM 决定调工具
        if finish_reason == "tool_calls":
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                return None
            tc = tool_calls[0]
            func = tc.get("function") or {}
            name = func.get("name", "")
            raw_args = func.get("arguments", "{}")
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                arguments = {}
            return {
                "type": "tool_call",
                "name": name,
                "arguments": arguments,
                # 原始 assistan message，用于追加到 messages 链
                "_assistant_msg": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {"name": name, "arguments": raw_args},
                        }
                    ],
                },
            }

        # LLM 直接给出文本回答
        content = msg.get("content") or ""
        if isinstance(content, str) and content.strip():
            return {"type": "text", "content": content.strip()}

        # 处理 reasoning model 的特殊情况
        reasoning_content = msg.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content.strip():
            logger.warning(
                "function_call: reasoning (%d chars) but empty content. finish=%s",
                len(reasoning_content), finish_reason,
            )
            return None

        return None

    def _chat_completion_raw(
        self,
        *,
        messages: list[dict],
        tools: list[dict] | None = None,
        provider_class: str = "routing",
    ) -> dict:
        """
        底层 LLM 调用，支持完整消息列表和 tools。

        Args:
            messages: 完整消息列表
            tools: 工具列表（可选）
            provider_class: "routing"(内部任务) | "user_facing"(用户可见回答)

        Returns:
            API 原始返回的 JSON dict
        """
        base_url, api_key, model = self._resolve_endpoint("deepseek-chat", provider_class=provider_class)
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

        body: dict = {
            "model": model,
            "messages": messages,
            "temperature": 0.35,
            "max_tokens": settings.llm_max_completion_tokens,
        }
        if tools:
            # 把 {name, description, parameters} 包装成 OpenAI tools 格式
            openai_tools = [
                {"type": "function", "function": t}
                for t in tools if isinstance(t, dict) and t.get("name")
            ]
            if openai_tools:
                body["tools"] = openai_tools
                body["tool_choice"] = "auto"

        logger.info(
            "LLM request: base_url=%s model=%s tools=%d api_key_last4=%s",
            base_url, model, len(tools or []),
            api_key[-4:] if api_key else "<empty>",
        )

        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url=f"{base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=settings.llm_request_timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _chat_completion(
        self,
        *,
        provider: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        provider_class: str = "routing",
    ) -> str:
        del provider

        base_url, api_key, model = self._resolve_endpoint(model, provider_class=provider_class)
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

        logger.info(
            "LLM request: provider=%s base_url=%s model=%s api_key_last4=%s",
            self._active_provider(), base_url, model,
            api_key[-4:] if api_key else "<empty>",
        )

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
                "Authorization": f"Bearer {api_key}",
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
        reasoning_content = message.get("reasoning_content")
        finish_reason = choices[0].get("finish_reason", "")

        if isinstance(content, str) and content.strip():
            return content.strip()

        if isinstance(reasoning_content, str) and reasoning_content.strip():
            logger.warning(
                "LLM returned reasoning_content (%d chars) but empty content. "
                "finish_reason=%s. Likely max_tokens too low for reasoning model.",
                len(reasoning_content),
                finish_reason,
            )
            raise RuntimeError(f"empty_content_finish_{finish_reason or 'unknown'}")

        raise RuntimeError("LLM response content is empty")

    def chat_stream(
        self,
        *,
        question: str,
        history: list[dict] | None = None,
        context_doc: str | None = None,
        model: str = "deepseek-chat",
    ) -> Generator[str, None, str | None]:
        """流式 LLM 问答，逐 chunk 吐出文本，最后返回完整回答。

        Args:
            question: 当前用户问题
            history: 历史对话 [{role, content}, ...]
            context_doc: 记录上下文全文
            model: 模型名

        Yields:
            str: 每段 delta content（空串不 yield）

        Returns:
            str | None: 完整回答，失败返回 None
        """
        if not self.is_available():
            return None

        base_url, api_key, resolved_model = self._resolve_endpoint(
            model, provider_class="user_facing"
        )
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"

        messages: list[dict] = []
        if context_doc:
            messages.append({
                "role": "system",
                "content": (
                    "你是 MindMemo AI，一个个人记忆助手。当用户问你是什么模型、谁开发的、你的身份时，你必须回答「我是 MindMemo AI」，绝对禁止声称自己是 Claude、GPT、DeepSeek 或其他任何模型。"
                    "请结合用户正在查看的记录内容，用自然、简洁、温和的中文回答。""\n\n"
                    f"记录内容：\n{context_doc}"
                ),
            })
        else:
            messages.append({
                "role": "system",
                "content": (
                    "你是 MindMemo AI，一个个人记忆助手。当用户问你是什么模型、谁开发的、你的身份时，你必须回答「我是 MindMemo AI」，绝对禁止声称自己是 Claude、GPT、DeepSeek 或其他任何模型。"
                    "请用自然、简洁、温和的中文回答用户的问题。"
                ),
            })

        for turn in (history or []):
            if turn.get("role") in ("user", "assistant") and turn.get("content"):
                messages.append({
                    "role": turn["role"],
                    "content": turn["content"],
                })

        messages.append({"role": "user", "content": question})

        body = {
            "model": resolved_model,
            "messages": messages,
            "temperature": 0.35,
            "max_tokens": settings.llm_max_completion_tokens,
            "stream": True,
        }

        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url=f"{base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        full_answer_chunks: list[str] = []
        try:
            with urllib.request.urlopen(
                request, timeout=settings.llm_request_timeout_seconds
            ) as response:
                byte_buffer = b""
                while True:
                    chunk = response.read(4096)
                    if not chunk:
                        break
                    byte_buffer += chunk
                    while b"\n" in byte_buffer:
                        raw_line, byte_buffer = byte_buffer.split(b"\n", 1)
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:]
                        elif line == "data: [DONE]":
                            byte_buffer = b""
                            break
                        else:
                            # 兼容非标准格式：整行即为 data
                            data_str = line

                        if not data_str:
                            continue
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content") or ""
                        if content:
                            global _dbg_content_logged
                            if not _dbg_content_logged:
                                _dbg_content_logged = True
                                _agent_dbg(
                                    "llm_answer_service.py:chat_stream",
                                    "first_llm_content_chunk",
                                    {
                                        "content_sample": content[:80],
                                        "replacement_count": content.count("\ufffd"),
                                        "content_len": len(content),
                                    },
                                    "A",
                                )
                            full_answer_chunks.append(content)
                            yield content
        except Exception as exc:
            logger.warning("LLM chat_stream failed: %s", exc)
            # 必须 re-raise 让调用方知道发生了错误，而不是 return None 静默终止
            raise

        full_answer = "".join(full_answer_chunks)
        return full_answer if full_answer else None


llm_answer_service = LLMAnswerService()
