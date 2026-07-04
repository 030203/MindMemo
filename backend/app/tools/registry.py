"""
工具注册中心 - 管理所有可用工具

核心职责：
1. 注册工具（自动或手动）
2. 根据名称获取工具实例
3. 导出工具列表供LLM使用

设计原则：
- 单例模式：全局唯一的工具注册中心
- 延迟加载：工具实例在需要时才创建
- 线程安全：支持并发注册和获取
"""
from typing import Type, Optional, Dict
from .base import BaseTool
import threading


class ToolRegistry:
    """
    工具注册中心 - 管理所有工具的生命周期

    使用示例：
        registry = ToolRegistry()
        registry.register(MyTool)
        tool = registry.get_tool("my_tool")
        result = await tool.execute(param="value")
    """

    def __init__(self):
        """初始化注册中心"""
        self._tool_classes: Dict[str, Type[BaseTool]] = {}
        self._tool_instances: Dict[str, BaseTool] = {}
        self._lock = threading.Lock()

    def register(self, tool_class: Type[BaseTool]) -> None:
        """
        注册工具类

        Args:
            tool_class: 工具类（继承自BaseTool）

        注意：
        - 同名工具会被覆盖
        - 注册的是类，不是实例（延迟实例化）
        """
        with self._lock:
            tool_name = tool_class.name
            self._tool_classes[tool_name] = tool_class
            # 清除旧实例（如果有）
            if tool_name in self._tool_instances:
                del self._tool_instances[tool_name]

    def register_instance(self, tool_instance: BaseTool) -> None:
        """
        注册工具实例（用于已配置好的工具）

        Args:
            tool_instance: 工具实例
        """
        with self._lock:
            tool_name = tool_instance.name
            self._tool_instances[tool_name] = tool_instance
            # 同时注册类（用于后续创建新实例）
            self._tool_classes[tool_name] = type(tool_instance)

    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """
        获取工具实例

        Args:
            tool_name: 工具名称

        Returns:
            工具实例，如果不存在返回None

        注意：
        - 第一次获取时会创建实例并缓存
        - 后续获取返回同一个实例（单例）
        """
        with self._lock:
            # 1. 先检查实例缓存
            if tool_name in self._tool_instances:
                return self._tool_instances[tool_name]

            # 2. 如果没有实例，从类创建
            if tool_name in self._tool_classes:
                tool_class = self._tool_classes[tool_name]
                tool_instance = tool_class()
                self._tool_instances[tool_name] = tool_instance
                return tool_instance

            # 3. 工具不存在
            return None

    def list_tools(self) -> list[str]:
        """
        列出所有已注册的工具名称

        Returns:
            工具名称列表
        """
        with self._lock:
            return list(self._tool_classes.keys())

    def list_tool_schemas(self) -> list[dict]:
        """
        列出所有工具的JSON Schema（供LLM使用）

        Returns:
            工具Schema列表

        示例：
            [
                {
                    "name": "search",
                    "description": "搜索工具",
                    "parameters": {...}
                },
                ...
            ]
        """
        schemas = []
        for tool_name in self.list_tools():
            tool = self.get_tool(tool_name)
            if tool:
                schemas.append(tool.to_json_schema())
        return schemas

    def unregister(self, tool_name: str) -> bool:
        """
        注销工具

        Args:
            tool_name: 工具名称

        Returns:
            是否成功注销
        """
        with self._lock:
            removed = False
            if tool_name in self._tool_classes:
                del self._tool_classes[tool_name]
                removed = True
            if tool_name in self._tool_instances:
                del self._tool_instances[tool_name]
                removed = True
            return removed

    def clear(self):
        """清空所有注册的工具"""
        with self._lock:
            self._tool_classes.clear()
            self._tool_instances.clear()


# 全局单例实例
_global_registry = ToolRegistry()


def get_global_registry() -> ToolRegistry:
    """获取全局工具注册中心"""
    return _global_registry
