"""
Agent基类 - 纯Python实现，无LangChain依赖

核心职责：
1. 定义Agent的统一接口
2. 管理Agent执行上下文
3. 提供工具调用能力
4. 记录执行轨迹（用于调试和可视化）

设计原则：
- 单一职责：Agent只负责决策，不做具体操作
- 依赖注入：MemoryManager和ToolRegistry通过构造函数传入
- 状态独立：每次execute()创建新的AgentContext，无全局状态
"""
from abc import ABC, abstractmethod
from typing import Any, Optional
from uuid import UUID
from dataclasses import dataclass, field
from datetime import datetime
from sqlalchemy.orm import Session


@dataclass
class AgentContext:
    """
    Agent执行上下文 - 替代LangChain的Memory

    职责：
    - 存储本次执行的中间状态
    - 记录工具调用历史
    - 管理推理轨迹（用于ReAct）

    注意：AgentContext是临时对象，仅在execute()生命周期内有效
    """
    user_id: UUID
    session_id: str
    start_time: datetime = field(default_factory=datetime.now)

    # 推理轨迹（用于ReAct多步推理）
    trajectory: list[dict] = field(default_factory=list)

    # 工具调用历史
    tool_calls: list[dict] = field(default_factory=list)

    # 中间变量（键值对，供Agent在多步推理中传递数据）
    variables: dict[str, Any] = field(default_factory=dict)

    # 执行元数据
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_thought(self, content: str):
        """添加推理步骤（Thought）"""
        self.trajectory.append({
            "type": "thought",
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

    def add_action(self, tool_name: str, tool_input: dict, observation: Any):
        """添加行动步骤（Action + Observation）"""
        action_record = {
            "type": "action",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "observation": observation,
            "timestamp": datetime.now().isoformat()
        }
        self.trajectory.append(action_record)
        self.tool_calls.append(action_record)

    def set_variable(self, key: str, value: Any):
        """设置中间变量（用于多步推理中的状态传递）"""
        self.variables[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        """获取中间变量"""
        return self.variables.get(key, default)

    def to_dict(self) -> dict:
        """导出为字典（用于序列化和日志记录）"""
        return {
            "user_id": str(self.user_id),
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat(),
            "trajectory_length": len(self.trajectory),
            "tool_calls_count": len(self.tool_calls),
            "variables": self.variables,
            "metadata": self.metadata
        }


class BaseAgent(ABC):
    """
    Agent基类 - 所有Agent的抽象父类

    子类需要实现：
    - execute(): 核心执行逻辑

    设计模式：模板方法模式
    - _pre_execute(): 执行前的准备工作（可选重写）
    - execute(): 核心逻辑（必须实现）
    - _post_execute(): 执行后的清理工作（可选重写）
    """

    def __init__(
        self,
        name: str,
        description: str,
        memory_manager: Optional[Any] = None,  # 避免循环导入，用Any
        tool_registry: Optional[Any] = None
    ):
        """
        初始化Agent

        Args:
            name: Agent名称（用于日志和调试）
            description: Agent功能描述
            memory_manager: 记忆管理器（可选，某些Agent不需要记忆）
            tool_registry: 工具注册中心（可选，某些Agent不需要工具）
        """
        self.name = name
        self.description = description
        self.memory_manager = memory_manager
        self.tool_registry = tool_registry

    @abstractmethod
    async def execute(
        self,
        db: Session,
        user_id: UUID,
        input_data: dict[str, Any],
        context: AgentContext
    ) -> dict[str, Any]:
        """
        执行Agent任务 - 核心接口，必须由子类实现

        Args:
            db: 数据库会话
            user_id: 用户ID
            input_data: 输入数据（不同Agent的输入格式不同）
            context: Agent执行上下文

        Returns:
            执行结果（字典格式，包含至少 status 和 data 字段）

        示例返回格式：
        {
            "status": "success" | "failed" | "partial",
            "data": {...},  # 具体业务数据
            "error": "错误信息"  # 可选，失败时包含
        }
        """
        pass

    async def run(
        self,
        db: Session,
        user_id: UUID,
        input_data: dict[str, Any],
        session_id: Optional[str] = None
    ) -> dict[str, Any]:
        """
        运行Agent - 完整生命周期管理（模板方法）

        这是外部调用的入口，内部会：
        1. 创建AgentContext
        2. 调用_pre_execute()
        3. 调用execute()
        4. 调用_post_execute()
        5. 持久化执行轨迹到数据库
        6. 返回结果

        Args:
            db: 数据库会话
            user_id: 用户ID
            input_data: 输入数据
            session_id: 会话ID（可选）

        Returns:
            执行结果
        """
        import uuid
        from datetime import datetime
        from app.models.agent_run import AgentRun

        # 1. 创建执行上下文
        context = AgentContext(
            user_id=user_id,
            session_id=session_id or self._generate_session_id()
        )

        try:
            # 2. 前置处理
            await self._pre_execute(db, user_id, input_data, context)

            # 3. 核心执行
            result = await self.execute(db, user_id, input_data, context)

            # 4. 后置处理
            await self._post_execute(db, user_id, result, context)

            # 5. 添加元数据
            duration_ms = (datetime.now() - context.start_time).total_seconds() * 1000
            result["_context"] = {
                "session_id": context.session_id,
                "trajectory_length": len(context.trajectory),
                "tool_calls_count": len(context.tool_calls),
                "duration_ms": duration_ms
            }

            # 6. 持久化轨迹
            try:
                agent_run = AgentRun(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    session_id=context.session_id,
                    agent_name=self.name,
                    question=input_data.get("question", input_data.get("message", "")),
                    answer=result.get("data", {}).get("answer", ""),
                    trajectory=context.trajectory,
                    tool_calls=context.tool_calls,
                    run_metadata=context.metadata,
                    duration_ms=int(duration_ms),
                    status=result.get("status", "success"),
                )
                db.add(agent_run)
                db.commit()
            except Exception:
                db.rollback()

            return result

        except Exception as e:
            # 错误处理
            return {
                "status": "failed",
                "error": str(e),
                "_context": {
                    "session_id": context.session_id,
                    "trajectory": context.trajectory
                }
            }

    async def _pre_execute(
        self,
        db: Session,
        user_id: UUID,
        input_data: dict[str, Any],
        context: AgentContext
    ):
        """
        执行前的准备工作（可选重写）

        典型用途：
        - 从MemoryManager加载必要的上下文
        - 参数验证
        - 权限检查
        """
        pass

    async def _post_execute(
        self,
        db: Session,
        user_id: UUID,
        result: dict[str, Any],
        context: AgentContext
    ):
        """
        执行后的清理工作（可选重写）

        典型用途：
        - 保存执行轨迹到数据库
        - 更新WorkingMemory
        - 发送监控指标
        """
        pass

    def _generate_session_id(self) -> str:
        """生成会话ID"""
        from uuid import uuid4
        return f"{self.name}_{uuid4().hex[:8]}"

    async def _call_tool(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        context: AgentContext
    ) -> Any:
        """
        调用工具 - 封装工具调用逻辑

        Args:
            tool_name: 工具名称
            tool_input: 工具输入参数
            context: Agent上下文

        Returns:
            工具执行结果

        Raises:
            ValueError: 工具不存在或参数错误
        """
        if not self.tool_registry:
            raise RuntimeError(f"Agent {self.name} 没有配置工具注册中心")

        tool = self.tool_registry.get_tool(tool_name)
        if not tool:
            raise ValueError(f"工具 {tool_name} 不存在")

        # 执行工具
        result = await tool.execute(**tool_input)

        # 记录到上下文
        context.add_action(tool_name, tool_input, result)

        return result
