"""
BaseTool和ToolRegistry单元测试

测试内容：
1. ToolParameter和ToolResult
2. BaseTool基本功能
3. ToolRegistry注册和获取
4. Tool Schema导出
"""
import pytest
from app.tools.base import (
    BaseTool,
    ToolResult,
    ToolParameter,
    ToolParameterType
)
from app.tools.registry import ToolRegistry, get_global_registry


# ============ ToolResult测试 ============

def test_tool_result_success():
    """测试成功的工具结果"""
    result = ToolResult(success=True, data={"value": 123})

    assert result.success is True
    assert result.data["value"] == 123
    assert result.error is None
    assert "success=True" in str(result)


def test_tool_result_failure():
    """测试失败的工具结果"""
    result = ToolResult(success=False, error="Something went wrong")

    assert result.success is False
    assert result.error == "Something went wrong"
    assert "success=False" in str(result)


# ============ BaseTool测试 ============

class SimpleTool(BaseTool):
    """简单测试工具"""
    name = "simple_tool"
    description = "一个简单的测试工具"
    parameters = [
        ToolParameter(
            name="text",
            type=ToolParameterType.STRING,
            description="输入文本",
            required=True
        ),
        ToolParameter(
            name="count",
            type=ToolParameterType.INTEGER,
            description="重复次数",
            required=False,
            default=1
        )
    ]

    async def execute(self, **kwargs) -> ToolResult:
        text = kwargs.get("text", "")
        count = kwargs.get("count", 1)

        if not text:
            return ToolResult(success=False, error="text不能为空")

        return ToolResult(
            success=True,
            data={"result": text * count}
        )


@pytest.mark.asyncio
async def test_simple_tool_execute():
    """测试工具执行"""
    tool = SimpleTool()

    result = await tool.execute(text="hello", count=3)

    assert result.success is True
    assert result.data["result"] == "hellohellohello"


@pytest.mark.asyncio
async def test_tool_with_default_param():
    """测试工具默认参数"""
    tool = SimpleTool()

    result = await tool.execute(text="hi")

    assert result.success is True
    assert result.data["result"] == "hi"


@pytest.mark.asyncio
async def test_tool_validation_error():
    """测试工具参数验证"""
    tool = SimpleTool()

    result = await tool.execute(text="")

    assert result.success is False
    assert "不能为空" in result.error


def test_tool_to_json_schema():
    """测试工具Schema导出"""
    tool = SimpleTool()

    schema = tool.to_json_schema()

    assert schema["name"] == "simple_tool"
    assert schema["description"] == "一个简单的测试工具"
    assert "text" in schema["parameters"]["properties"]
    assert "count" in schema["parameters"]["properties"]
    assert "text" in schema["parameters"]["required"]
    assert "count" not in schema["parameters"]["required"]


def test_tool_validate_parameters():
    """测试参数验证"""
    tool = SimpleTool()

    # 缺少必填参数
    valid, error = tool.validate_parameters(count=2)
    assert valid is False
    assert "text" in error

    # 多余参数
    valid, error = tool.validate_parameters(text="hi", unknown="param")
    assert valid is False
    assert "unknown" in error

    # 正确参数
    valid, error = tool.validate_parameters(text="hi")
    assert valid is True
    assert error is None


# ============ ToolRegistry测试 ============

def test_registry_register_class():
    """测试注册工具类"""
    registry = ToolRegistry()

    registry.register(SimpleTool)

    assert "simple_tool" in registry.list_tools()


def test_registry_get_tool():
    """测试获取工具实例"""
    registry = ToolRegistry()
    registry.register(SimpleTool)

    tool = registry.get_tool("simple_tool")

    assert tool is not None
    assert isinstance(tool, SimpleTool)

    # 第二次获取应该返回同一个实例（单例）
    tool2 = registry.get_tool("simple_tool")
    assert tool is tool2


def test_registry_get_nonexistent_tool():
    """测试获取不存在的工具"""
    registry = ToolRegistry()

    tool = registry.get_tool("nonexistent")

    assert tool is None


def test_registry_register_instance():
    """测试注册工具实例"""
    registry = ToolRegistry()
    tool_instance = SimpleTool()

    registry.register_instance(tool_instance)

    retrieved = registry.get_tool("simple_tool")
    assert retrieved is tool_instance


def test_registry_list_tool_schemas():
    """测试列出所有工具Schema"""
    registry = ToolRegistry()
    registry.register(SimpleTool)

    schemas = registry.list_tool_schemas()

    assert len(schemas) == 1
    assert schemas[0]["name"] == "simple_tool"
    assert "parameters" in schemas[0]


def test_registry_unregister():
    """测试注销工具"""
    registry = ToolRegistry()
    registry.register(SimpleTool)

    assert "simple_tool" in registry.list_tools()

    success = registry.unregister("simple_tool")

    assert success is True
    assert "simple_tool" not in registry.list_tools()


def test_registry_clear():
    """测试清空注册表"""
    registry = ToolRegistry()
    registry.register(SimpleTool)

    registry.clear()

    assert len(registry.list_tools()) == 0


def test_global_registry():
    """测试全局单例"""
    registry1 = get_global_registry()
    registry2 = get_global_registry()

    assert registry1 is registry2


# ============ 多工具测试 ============

class AnotherTool(BaseTool):
    """另一个测试工具"""
    name = "another_tool"
    description = "另一个工具"
    parameters = []

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, data={})


def test_registry_multiple_tools():
    """测试注册多个工具"""
    registry = ToolRegistry()

    registry.register(SimpleTool)
    registry.register(AnotherTool)

    tools = registry.list_tools()

    assert len(tools) == 2
    assert "simple_tool" in tools
    assert "another_tool" in tools

    # 验证可以分别获取
    tool1 = registry.get_tool("simple_tool")
    tool2 = registry.get_tool("another_tool")

    assert isinstance(tool1, SimpleTool)
    assert isinstance(tool2, AnotherTool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
