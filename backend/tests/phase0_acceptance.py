"""
Phase 0 验收脚本 - 快速验证基础设施

运行此脚本验证Phase 0的所有核心功能
"""
import sys
import asyncio
from uuid import uuid4


def test_imports():
    """测试所有模块能否正常导入"""
    print("✓ 测试模块导入...")

    try:
        from app.agent.base import BaseAgent, AgentContext
        from app.tools.base import BaseTool, ToolResult, ToolParameter, ToolParameterType
        from app.tools.registry import ToolRegistry, get_global_registry
        from app.memory.manager import MemoryManager
        from app.memory.layers.working import WorkingMemory
        from app.llm.client import LLMClient

        print("  ✅ 所有模块导入成功")
        return True
    except ImportError as e:
        print(f"  ❌ 模块导入失败: {e}")
        return False


def test_agent_context():
    """测试AgentContext基本功能"""
    print("✓ 测试AgentContext...")

    from app.agent.base import AgentContext

    ctx = AgentContext(user_id=uuid4(), session_id="test")

    # 测试推理轨迹
    ctx.add_thought("测试思考")
    assert len(ctx.trajectory) == 1

    # 测试行动记录
    ctx.add_action("test_tool", {"param": "value"}, {"result": "ok"})
    assert len(ctx.tool_calls) == 1

    # 测试变量管理
    ctx.set_variable("key", "value")
    assert ctx.get_variable("key") == "value"

    print("  ✅ AgentContext 功能正常")
    return True


async def test_agent_lifecycle():
    """测试Agent生命周期"""
    print("✓ 测试Agent生命周期...")

    from app.agent.base import BaseAgent, AgentContext

    class TestAgent(BaseAgent):
        async def execute(self, db, user_id, input_data, context):
            context.add_thought("执行中")
            return {"status": "success", "data": {"message": "ok"}}

    agent = TestAgent(name="test", description="测试Agent")
    result = await agent.run(db=None, user_id=uuid4(), input_data={})

    assert result["status"] == "success"
    assert "_context" in result

    print("  ✅ Agent 生命周期正常")
    return True


async def test_tool_system():
    """测试工具系统"""
    print("✓ 测试工具系统...")

    from app.tools.base import BaseTool, ToolResult, ToolParameter, ToolParameterType
    from app.tools.registry import ToolRegistry

    # 定义测试工具
    class EchoTool(BaseTool):
        name = "echo"
        description = "回显工具"
        parameters = [
            ToolParameter(
                name="text",
                type=ToolParameterType.STRING,
                description="输入文本",
                required=True
            )
        ]

        async def execute(self, **kwargs) -> ToolResult:
            return ToolResult(success=True, data={"echo": kwargs.get("text", "")})

    # 测试工具执行
    tool = EchoTool()
    result = await tool.execute(text="hello")
    assert result.success is True
    assert result.data["echo"] == "hello"

    # 测试Schema导出
    schema = tool.to_json_schema()
    assert schema["name"] == "echo"
    assert "text" in schema["parameters"]["required"]

    # 测试注册中心
    registry = ToolRegistry()
    registry.register(EchoTool)

    retrieved = registry.get_tool("echo")
    assert retrieved is not None

    schemas = registry.list_tool_schemas()
    assert len(schemas) == 1

    print("  ✅ 工具系统正常")
    return True


def test_memory_system():
    """测试记忆系统"""
    print("✓ 测试记忆系统...")

    from app.memory.manager import MemoryManager
    from app.memory.layers.working import WorkingMemory

    # 测试WorkingMemory
    wm = WorkingMemory(max_size=5)
    wm.add_turn("user", "你好")
    wm.add_turn("assistant", "你好，有什么可以帮助你的？")
    wm.set_context("session_id", "test_123")

    history = wm.get_recent_turns(n=2)
    assert len(history) == 2

    context = wm.get_context("session_id")
    assert context == "test_123"

    # 测试MemoryManager
    mm = MemoryManager(db=None, user_id=uuid4())

    # 访问WorkingMemory（延迟加载）
    mm.working.add_turn("user", "测试消息")

    # 获取Router上下文
    ctx = mm.get_context_for_router()
    assert "recent_conversation" in ctx
    assert "active_goals" in ctx

    print("  ✅ 记忆系统正常")
    return True


async def test_agent_tool_integration():
    """测试Agent和Tool集成"""
    print("✓ 测试Agent-Tool集成...")

    from app.agent.base import BaseAgent, AgentContext
    from app.tools.base import BaseTool, ToolResult, ToolParameter, ToolParameterType
    from app.tools.registry import ToolRegistry

    # 定义工具
    class UppercaseTool(BaseTool):
        name = "uppercase"
        description = "转大写工具"
        parameters = [
            ToolParameter(
                name="text",
                type=ToolParameterType.STRING,
                description="输入文本",
                required=True
            )
        ]

        async def execute(self, **kwargs) -> ToolResult:
            text = kwargs.get("text", "")
            return ToolResult(success=True, data={"result": text.upper()})

    # 定义Agent
    class ToolUsingAgent(BaseAgent):
        async def execute(self, db, user_id, input_data, context):
            # 调用工具
            result = await self._call_tool(
                "uppercase",
                {"text": input_data.get("text", "")},
                context
            )

            return {
                "status": "success",
                "data": {"uppercase": result.data["result"]}
            }

    # 创建注册中心并注册工具
    registry = ToolRegistry()
    registry.register(UppercaseTool)

    # 创建Agent
    agent = ToolUsingAgent(
        name="test_agent",
        description="测试Agent",
        tool_registry=registry
    )

    # 运行
    result = await agent.run(
        db=None,
        user_id=uuid4(),
        input_data={"text": "hello"}
    )

    assert result["status"] == "success"
    assert result["data"]["uppercase"] == "HELLO"
    assert result["_context"]["tool_calls_count"] == 1

    print("  ✅ Agent-Tool 集成正常")
    return True


async def main():
    """主测试流程"""
    print("\n" + "="*60)
    print("Phase 0 验收测试")
    print("="*60 + "\n")

    tests = [
        ("模块导入", test_imports),
        ("AgentContext", test_agent_context),
        ("Agent生命周期", test_agent_lifecycle),
        ("工具系统", test_tool_system),
        ("记忆系统", test_memory_system),
        ("Agent-Tool集成", test_agent_tool_integration),
    ]

    results = []

    for name, test_func in tests:
        try:
            if asyncio.iscoroutinefunction(test_func):
                success = await test_func()
            else:
                success = test_func()
            results.append((name, success))
        except Exception as e:
            print(f"  ❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # 打印总结
    print("\n" + "="*60)
    print("测试总结")
    print("="*60)

    passed = sum(1 for _, success in results if success)
    total = len(results)

    for name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"  {status}: {name}")

    print(f"\n总计: {passed}/{total} 测试通过")

    if passed == total:
        print("\n🎉 Phase 0 验收完成！所有测试通过！")
        print("\n下一步：开始 Phase 1 - 分层记忆重构")
        return 0
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败，请检查")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
