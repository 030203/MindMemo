# MindMemo 架构重构计划书 v1.1 (Pure Python)

**版本更新**: v1.0 → v1.1 - 移除 LangChain 依赖，纯手工实现  
**重构目标**: Multi-Agent架构 + 分层记忆 + 1.2s延迟控制  
**策略**: 渐进式重构，模块解耦，充分注释，便于独立测试  
**预计周期**: 12周（3个月）

---

## 技术选型变更

### v1.0 → v1.1 主要变化

| 模块 | v1.0 (LangChain) | v1.1 (Pure Python) | 原因 |
|------|------------------|-------------------|------|
| Agent框架 | LangChain + LangGraph | 手工实现 Agent 基类 + 状态机 | 避免黑盒，完全可控，易调试 |
| ReAct循环 | LangChain ReAct | 自己写推理循环 | 简化依赖，降低学习成本 |
| 工具调用 | LangChain Tools | 自定义 Tool 协议 + JSON Schema | 轻量，无过度抽象 |
| Prompt管理 | LangChain PromptTemplate | 纯字符串模板 + Jinja2 | 灵活，易于版本控制 |
| LLM调用 | LangChain LLM Wrapper | 直接用 OpenAI SDK | 减少中间层，性能更优 |
| 记忆管理 | LangChain Memory | 自己实现分层记忆 | 完全掌控，符合业务需求 |

### 保持不变的技术栈

- **LLM**: OpenAI GPT-4 (推理) + GPT-3.5 (快速)
- **数据库**: PostgreSQL / SQLite
- **向量检索**: 现有 embedding_service
- **任务队列**: Celery + Redis
- **缓存**: Redis
- **监控**: Prometheus + Grafana

---

## 核心架构（不变）

```
┌─────────────────────────────────────────────────────────────┐
│                    SHARED MEMORY (横向共享层)                 │
│  Working | Episodic | Semantic | Goal | Procedural | Insights │
└─────────────────────────────────────────────────────────────┘
              ▲               ▲               ▲
              │               │               │
┌─────────────┴───────────────┴───────────────┴──────────────┐
│  USER → Router ─┬─ fast ──→ QA Agent (单轮)                 │
│                 └─ slow ──→ Planner → ReAct Agent (多轮)    │
│                                │                             │
│                                ▼                             │
│                         Tool Registry                        │
│                   (纯Python实现，无LangChain)                 │
│                                                              │
│  [异步] Insight Agent / Memory Manager                       │
└──────────────────────────────────────────────────────────────┘
```

---

## Phase 0: 基础设施准备（立即开始）

### 目标
搭建纯 Python 的 Agent/Tool/Memory 骨架，**充分注释**，模块解耦，便于独立测试。

### 技术实现细节

#### 0.1 目录结构（复用现有）

```
backend/app/
├── agent/                       # 🆕 Agent层（复用 app/agents/ 或新建）
│   ├── __init__.py
│   ├── base.py                  # Agent基类（纯Python状态机）
│   ├── context.py               # AgentContext（执行上下文，替代LangChain Memory）
│   ├── router.py                # 路由器
│   ├── qa_agent.py              # 单轮问答Agent
│   ├── react_agent.py           # ReAct推理Agent
│   ├── insight_agent.py         # 洞察Agent
│   └── planner.py               # 任务规划器
│
├── memory/                      # 🆕 记忆系统
│   ├── __init__.py
│   ├── manager.py               # 统一记忆管理器
│   ├── layers/
│   │   ├── __init__.py
│   │   ├── working.py           # Working Memory（会话上下文）
│   │   ├── episodic.py          # Episodic Memory
│   │   ├── semantic.py          # Semantic Memory
│   │   ├── goal.py              # Goal Memory (新)
│   │   ├── procedural.py        # Procedural Memory
│   │   └── insight.py           # Insight Cache
│   └── types.py                 # 数据类型定义
│
├── tools/                       # 🆕 工具系统（纯Python，无LangChain）
│   ├── __init__.py
│   ├── registry.py              # 工具注册中心
│   ├── base.py                  # Tool基类
│   ├── types.py                 # ToolParameter, ToolResult
│   ├── retrieval/               # 检索工具
│   │   ├── __init__.py
│   │   ├── hybrid_search.py
│   │   ├── time_resolver.py
│   │   └── fact_extractor.py
│   ├── memory/                  # 记忆工具
│   │   ├── __init__.py
│   │   └── relation_finder.py
│   └── external/                # 外部工具
│       ├── __init__.py
│       ├── web_search.py
│       └── weather.py
│
├── orchestration/               # 🆕 编排层（复用 workflows/ 或新建）
│   ├── __init__.py
│   ├── workflow.py              # 工作流基类
│   ├── qa_workflow.py           # 问答流程编排
│   └── insight_workflow.py      # 洞察流程编排
│
└── llm/                         # 🆕 LLM调用封装（纯OpenAI SDK）
    ├── __init__.py
    ├── client.py                # LLM客户端封装
    ├── prompts.py               # Prompt模板管理
    └── parser.py                # 输出解析（JSON/思维链）
```

---

### 0.2 核心基类设计

#### Agent 基类（无 LangChain）

```python
# app/agent/base.py
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

from app.memory.manager import MemoryManager
from app.tools.registry import ToolRegistry


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
        memory_manager: Optional[MemoryManager] = None,
        tool_registry: Optional[ToolRegistry] = None
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
        5. 返回结果
        
        Args:
            db: 数据库会话
            user_id: 用户ID
            input_data: 输入数据
            session_id: 会话ID（可选）
            
        Returns:
            执行结果
        """
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
            result["_context"] = {
                "session_id": context.session_id,
                "trajectory_length": len(context.trajectory),
                "tool_calls_count": len(context.tool_calls),
                "duration_ms": (datetime.now() - context.start_time).total_seconds() * 1000
            }
            
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
    
    def _call_tool(
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
        result = tool.execute(**tool_input)
        
        # 记录到上下文
        context.add_action(tool_name, tool_input, result)
        
        return result
```

---

#### Tool 基类（无 LangChain）

```python
# app/tools/base.py
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
            prop_schema = {
                "type": param.type.value,
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
```

---

### 0.3 任务清单

- [x] 创建目录结构
- [ ] 实现 `BaseAgent` 和 `AgentContext`
- [ ] 实现 `BaseTool` 和 `ToolResult`
- [ ] 实现 `MemoryManager` 骨架
- [ ] 实现 `ToolRegistry` 骨架
- [ ] 实现 `LLMClient` 封装（纯OpenAI SDK）
- [ ] 编写单元测试
- [ ] 编写集成测试示例

---

### 0.4 验收标准

```python
# 测试代码：能成功导入和实例化
from app.agent.base import BaseAgent, AgentContext
from app.tools.base import BaseTool, ToolResult
from app.memory.manager import MemoryManager
from app.tools.registry import ToolRegistry

# 实例化测试
context = AgentContext(user_id=UUID("..."), session_id="test")
context.add_thought("这是一个测试")
assert len(context.trajectory) == 1

# 工具Schema导出测试
class DummyTool(BaseTool):
    name = "dummy"
    description = "测试工具"
    parameters = [
        ToolParameter(name="query", type="string", required=True)
    ]
    
    async def execute(self, query: str) -> ToolResult:
        return ToolResult(success=True, data={"result": query})

tool = DummyTool()
schema = tool.to_json_schema()
assert schema["name"] == "dummy"
assert "query" in schema["parameters"]["required"]
```

---

## 下一步行动

1. ✅ 已创建计划书 v1.1
2. ⏭️ **立即开始 Phase 0**：搭建骨架
   - 创建目录
   - 实现 `BaseAgent`
   - 实现 `BaseTool`
   - 实现 `MemoryManager` 骨架
   - 实现 `ToolRegistry` 骨架
   - 实现 `LLMClient` 封装

准备好了吗？我现在开始写代码！🚀
