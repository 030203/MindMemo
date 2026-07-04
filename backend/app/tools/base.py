"""
Tool基类 - 纯Python实现，无LangChain依赖

核心职责：
1. 定义工具的统一接口
2. 提供JSON Schema导出（供LLM理解工具功能）
3. 参数校验

设计原则：
- 输入输出标准化：所有工具返回ToolResult
- 自描述：工具通过metadata描述自己的能力
- 无状态：工具不保存状态，便于并发调用
"""
from abc import ABC, abstractmethod
from typing import Any, Optional
from pydantic import BaseModel, Field
from enum import Enum


class ToolParameterType(str, Enum):
    """工具参数类型枚举"""
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


class ToolParameter(BaseModel):
    """
    工具参数定义

    用于生成JSON Schema，让LLM理解工具需要什么参数
    """
    name: str
    type: ToolParameterType
    description: str
    required: bool = False
    default: Optional[Any] = None
    enum: Optional[list[Any]] = None  # 枚举值（可选）

    class Config:
        use_enum_values = True


class ToolResult(BaseModel):
    """
    工具执行结果 - 标准化返回格式

    所有工具必须返回此格式，便于：
    1. Agent统一处理
    2. 错误追踪
    3. 结果可视化
    """
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def __str__(self) -> str:
        """字符串表示（用于日志和调试）"""
        if self.success:
            return f"ToolResult(success=True, data={self.data})"
        else:
            return f"ToolResult(success=False, error={self.error})"


class BaseTool(ABC):
    """
    工具基类 - 所有工具的抽象父类

    子类需要定义：
    - name: 工具名称（类属性）
    - description: 工具描述（类属性）
    - parameters: 参数列表（类属性）

    子类需要实现：
    - execute(): 核心执行逻辑
    """

    name: str = "base_tool"  # 子类必须重写
    description: str = "Base tool"  # 子类必须重写
    parameters: list[ToolParameter] = []  # 子类必须重写

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """
        执行工具 - 核心接口，必须由子类实现

        Args:
            **kwargs: 工具参数（与self.parameters定义的参数对应）

        Returns:
            ToolResult: 执行结果

        注意：
        - 参数名必须与self.parameters中定义的name一致
        - 必须返回ToolResult，不要抛异常（在ToolResult.error中返回错误）
        """
        pass

    def to_json_schema(self) -> dict:
        """
        导出为JSON Schema格式（供LLM使用）

        返回格式符合OpenAI Function Calling规范：
        {
            "name": "tool_name",
            "description": "工具描述",
            "parameters": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string", "description": "..."},
                    ...
                },
                "required": ["param1", ...]
            }
        }
        """
        properties = {}
        required = []

        for param in self.parameters:
            # use_enum_values=True means param.type is already a string
            prop_schema = {
                "type": param.type,
                "description": param.description
            }

            if param.enum:
                prop_schema["enum"] = param.enum

            if param.default is not None:
                prop_schema["default"] = param.default

            properties[param.name] = prop_schema

            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }

    def validate_parameters(self, **kwargs) -> tuple[bool, Optional[str]]:
        """
        验证参数 - 检查必填参数和类型

        Returns:
            (is_valid, error_message)
        """
        param_dict = {p.name: p for p in self.parameters}

        # 检查必填参数
        for param in self.parameters:
            if param.required and param.name not in kwargs:
                return False, f"缺少必填参数: {param.name}"

        # 检查多余参数
        for key in kwargs:
            if key not in param_dict:
                return False, f"未知参数: {key}"

        # TODO: 可以添加类型检查（暂时省略，Pydantic可以做）

        return True, None
