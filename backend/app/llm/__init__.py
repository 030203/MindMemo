"""
LLM模块 - LLM调用封装（纯OpenAI SDK）

包含：
- LLMClient: LLM客户端封装
- Prompts: Prompt模板管理
- Parser: 输出解析（JSON/思维链）
"""

from .client import LLMClient

__all__ = ["LLMClient"]
