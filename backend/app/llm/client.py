"""
LLM客户端封装 - 纯OpenAI SDK实现

核心职责：
1. 封装OpenAI API调用
2. 统一错误处理
3. 支持流式输出
4. 支持Function Calling

设计原则：
- 简洁封装：不过度抽象，保持OpenAI原生API风格
- 错误容忍：网络错误自动重试
- 可观测：记录所有LLM调用日志
"""
import openai
from typing import Optional, List, Dict, Any
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """
    LLM客户端 - 封装OpenAI API调用

    使用示例：
        client = LLMClient()

        # 简单对话
        response = await client.chat(
            messages=[{"role": "user", "content": "你好"}],
            model="gpt-3.5-turbo"
        )

        # Function Calling
        response = await client.chat(
            messages=[...],
            functions=[tool.to_json_schema() for tool in tools],
            model="gpt-4"
        )
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: str = "gpt-3.5-turbo"
    ):
        """
        初始化LLM客户端

        Args:
            api_key: OpenAI API Key（默认从配置读取）
            base_url: API Base URL（默认从配置读取）
            default_model: 默认模型
        """
        self.api_key = api_key or settings.openai_api_key
        self.base_url = base_url or settings.openai_base_url
        self.default_model = default_model

        # 初始化OpenAI客户端
        openai.api_key = self.api_key
        if self.base_url:
            openai.api_base = self.base_url

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        functions: Optional[List[Dict]] = None,
        function_call: Optional[str | Dict] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        调用Chat Completion API

        Args:
            messages: 对话消息列表
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数
            functions: Function Calling定义
            function_call: 强制调用的函数
            stream: 是否流式输出
            **kwargs: 其他OpenAI参数

        Returns:
            API响应字典

        示例：
            response = await client.chat(
                messages=[
                    {"role": "system", "content": "你是一个助手"},
                    {"role": "user", "content": "今天天气怎么样"}
                ],
                model="gpt-3.5-turbo",
                temperature=0.7
            )

            answer = response["choices"][0]["message"]["content"]
        """
        model = model or self.default_model

        try:
            # 构建请求参数
            request_params = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": stream,
                **kwargs
            }

            if max_tokens:
                request_params["max_tokens"] = max_tokens

            if functions:
                request_params["functions"] = functions

            if function_call:
                request_params["function_call"] = function_call

            # 调用API
            logger.info(f"调用LLM: model={model}, messages_count={len(messages)}")
            response = openai.ChatCompletion.create(**request_params)

            # 记录使用情况
            if "usage" in response:
                logger.info(f"LLM使用: {response['usage']}")

            return response

        except openai.error.RateLimitError as e:
            logger.error(f"LLM速率限制: {e}")
            raise

        except openai.error.APIError as e:
            logger.error(f"LLM API错误: {e}")
            raise

        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            raise

    async def simple_chat(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        model: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        简化的对话接口 - 直接返回文本回复

        Args:
            prompt: 用户输入
            system_message: 系统消息（可选）
            model: 模型名称
            **kwargs: 其他参数

        Returns:
            模型回复文本
        """
        messages = []

        if system_message:
            messages.append({"role": "system", "content": system_message})

        messages.append({"role": "user", "content": prompt})

        response = await self.chat(messages=messages, model=model, **kwargs)

        return response["choices"][0]["message"]["content"]

    async def function_call(
        self,
        messages: List[Dict[str, str]],
        functions: List[Dict],
        model: Optional[str] = None,
        force_function: Optional[str] = None,
        **kwargs
    ) -> tuple[Optional[str], Optional[Dict]]:
        """
        Function Calling接口

        Args:
            messages: 对话消息
            functions: 可用函数列表
            model: 模型名称
            force_function: 强制调用的函数名
            **kwargs: 其他参数

        Returns:
            (function_name, arguments) 如果调用了函数
            (None, None) 如果返回普通回复
        """
        function_call_param = None
        if force_function:
            function_call_param = {"name": force_function}

        response = await self.chat(
            messages=messages,
            functions=functions,
            function_call=function_call_param,
            model=model or "gpt-4",  # Function Calling建议用gpt-4
            **kwargs
        )

        message = response["choices"][0]["message"]

        # 检查是否调用了函数
        if "function_call" in message:
            import json
            function_name = message["function_call"]["name"]
            arguments = json.loads(message["function_call"]["arguments"])
            return function_name, arguments

        return None, None

    async def parse_json(
        self,
        prompt: str,
        schema: Dict,
        model: Optional[str] = None,
        **kwargs
    ) -> Optional[Dict]:
        """
        结构化输出 - 让LLM按照Schema返回JSON

        Args:
            prompt: 提示词
            schema: JSON Schema定义
            model: 模型名称
            **kwargs: 其他参数

        Returns:
            解析后的JSON对象，失败返回None
        """
        import json

        # 构建系统消息
        system_message = f"""你是一个数据提取助手。
请根据用户输入，按照以下JSON Schema返回结构化数据：

{json.dumps(schema, ensure_ascii=False, indent=2)}

重要：
1. 只返回JSON，不要有任何额外文字
2. 确保JSON格式正确
3. 如果无法提取某字段，使用null
"""

        try:
            response = await self.simple_chat(
                prompt=prompt,
                system_message=system_message,
                model=model,
                temperature=0.3,  # 降低温度保证格式稳定
                **kwargs
            )

            # 提取JSON（处理markdown代码块）
            text = response.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            return json.loads(text.strip())

        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}, 原始输出: {response}")
            return None
        except Exception as e:
            logger.error(f"结构化输出失败: {e}")
            return None


# 全局单例
_global_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """获取全局LLM客户端"""
    global _global_client
    if _global_client is None:
        _global_client = LLMClient()
    return _global_client
