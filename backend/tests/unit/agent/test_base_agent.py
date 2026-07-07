"""
BaseAgent和AgentContext单元测试

测试内容：
1. AgentContext基本功能
2. BaseAgent生命周期管理
3. 工具调用机制
"""
import pytest
from uuid import uuid4
from datetime import datetime
from app.agent.base import BaseAgent, AgentContext
from app.tools.base import BaseTool, ToolResult, ToolParameter, ToolParameterType
from app.tools.registry import ToolRegistry


# ============ AgentContext测试 ============

def test_agent_context_creation():
    """测试AgentContext创建"""
    user_id = uuid4()
    ctx = AgentContext(user_id=user_id, session_id="test_session")

    assert ctx.user_id == user_id
    assert ctx.session_id == "test_session"
    assert len(ctx.trajectory) == 0
    assert len(ctx.tool_calls) == 0


def test_agent_context_add_thought():
    """测试添加推理步骤"""
    ctx = AgentContext(user_id=uuid4(), session_id="test")

    ctx.add_thought("我需要搜索相关记忆")

    assert len(ctx.trajectory) == 1
    assert ctx.trajectory[0]["type"] == "thought"
    assert "搜索相关记忆" in ctx.trajectory[0]["content"]


def test_agent_context_add_action():
    """测试添加行动步骤"""
    ctx = AgentContext(user_id=uuid4(), session_id="test")

    ctx.add_action(
        tool_name="search",
        tool_input={"query": "测试"},
        observation={"results": []}
    )

    assert len(ctx.trajectory) == 1
    assert len(ctx.tool_calls) == 1
    assert ctx.trajectory[0]["type"] == "action"
    assert ctx.tool_calls[0]["tool_name"] == "search"


def test_agent_context_variables():
    """测试中间变量管理"""
    ctx = AgentContext(user_id=uuid4(), session_id="test")

    ctx.set_variable("search_results", ["result1", "result2"])
    assert ctx.get_variable("search_results") == ["result1", "result2"]
    assert ctx.get_variable("nonexistent", "default") == "default"


def test_agent_context_to_dict():
    """测试序列化"""
    ctx = AgentContext(user_id=uuid4(), session_id="test")
    ctx.add_thought("测试")
    ctx.set_variable("key", "value")

    data = ctx.to_dict()

    assert "user_id" in data
    assert data["session_id"] == "test"
    assert data["trajectory_length"] == 1
    assert data["variables"]["key"] == "value"


# ============ BaseAgent测试 ============

class DummyAgent(BaseAgent):
    """测试用的Agent实现"""

    async def execute(self, db, user_id, input_data, context):
        # 简单实现：返回输入数据
        context.add_thought("开始执行")
        return {
            "status": "success",
            "data": {"echo": input_data.get("message", "")}
        }


@pytest.mark.asyncio
async def test_base_agent_run():
    """测试Agent完整运行"""
    agent = DummyAgent(name="dummy", description="测试Agent")

    result = await agent.run(
        db=None,  # DummyAgent不需要db
        user_id=uuid4(),
        input_data={"message": "hello"}
    )

    assert result["status"] == "success"
    assert result["data"]["echo"] == "hello"
    assert "_context" in result
    assert result["_context"]["trajectory_length"] == 1


@pytest.mark.asyncio
async def test_base_agent_with_pre_post():
    """测试Agent前后置处理"""

    class AgentWithHooks(BaseAgent):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.pre_called = False
            self.post_called = False

        async def _pre_execute(self, db, user_id, input_data, context):
            self.pre_called = True
            context.set_variable("pre_executed", True)

        async def execute(self, db, user_id, input_data, context):
            assert context.get_variable("pre_executed") is True
            return {"status": "success", "data": {}}

        async def _post_execute(self, db, user_id, result, context):
            self.post_called = True

    agent = AgentWithHooks(name="test", description="测试")

    await agent.run(db=None, user_id=uuid4(), input_data={})

    assert agent.pre_called
    assert agent.post_called


@pytest.mark.asyncio
async def test_base_agent_error_handling():
    """测试Agent错误处理"""

    class FailingAgent(BaseAgent):
        async def execute(self, db, user_id, input_data, context):
            raise ValueError("测试错误")

    agent = FailingAgent(name="failing", description="会失败的Agent")

    result = await agent.run(db=None, user_id=uuid4(), input_data={})

    assert result["status"] == "failed"
    assert "测试错误" in result["error"]


# ============ Agent工具调用测试 ============

class DummyTool(BaseTool):
    """测试用工具"""
    name = "dummy_tool"
    description = "测试工具"
    parameters = [
        ToolParameter(
            name="input",
            type=ToolParameterType.STRING,
            description="输入参数",
            required=True
        )
    ]

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            data={"output": kwargs.get("input", "").upper()}
        )


@pytest.mark.asyncio
async def test_agent_call_tool():
    """测试Agent调用工具"""

    # 创建工具注册中心
    registry = ToolRegistry()
    registry.register(DummyTool)

    class ToolCallingAgent(BaseAgent):
        async def execute(self, db, user_id, input_data, context):
            # 调用工具
            result = await self._call_tool(
                "dummy_tool",
                {"input": "hello"},
                context
            )

            return {
                "status": "success",
                "data": {"tool_result": result.data}
            }

    agent = ToolCallingAgent(
        name="tool_caller",
        description="调用工具的Agent",
        tool_registry=registry
    )

    result = await agent.run(db=None, user_id=uuid4(), input_data={})

    assert result["status"] == "success"
    assert result["data"]["tool_result"]["output"] == "HELLO"
    assert result["_context"]["tool_calls_count"] == 1


@pytest.mark.asyncio
async def test_agent_call_nonexistent_tool():
    """测试调用不存在的工具"""

    registry = ToolRegistry()

    class ToolCallingAgent(BaseAgent):
        async def execute(self, db, user_id, input_data, context):
            await self._call_tool("nonexistent", {}, context)
            return {"status": "success"}

    agent = ToolCallingAgent(
        name="test",
        description="test",
        tool_registry=registry
    )

    result = await agent.run(db=None, user_id=uuid4(), input_data={})

    assert result["status"] == "failed"
    assert "不存在" in result["error"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
