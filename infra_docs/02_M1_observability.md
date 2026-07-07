# M1 — 全链路可观测性（LLM Tracing）

> **一句话**：给 Agent / Tool / LLM 三层加统一 span 埋点，把已有的 `AgentRun` 轨迹升级为可查询、可回放、带 token/延迟的分布式 trace。
>
> **改造对象**：`agent/base.py`、`services/llm_answer_service.py`、新增 `app/observability/`
> **不碰**：任何业务 Agent（QAAgent/ReActAgent）的逻辑 —— 埋点全部在基类和 LLM 层完成。

---

## 1. 为什么先做这个

后面每一个 Milestone 的收益（重试成功率、缓存命中率、成本下降、评估分数）都要靠数据证明。没有 tracing，优化就是盲改。M1 是所有其他 Milestone 的"眼睛"，所以排第一。

而且它**零业务风险**：纯增量埋点，失败静默降级，不改变任何回答逻辑。

---

## 2. 设计：轻量自建 Trace 上下文 + 可选 Langfuse 导出

不强依赖第三方。核心是一个进程内的 `TraceContext`（基于 `contextvars`，天然协程安全），可选把 span 导出到 Langfuse / OTel。

```
app/observability/
├── __init__.py
├── trace.py          # TraceContext + Span，基于 contextvars
├── exporters.py      # 导出器：DBExporter(默认) / LangfuseExporter(可选) / NoopExporter
└── decorators.py     # @traced_span 装饰器 + 上下文管理器
```

### 2.1 数据模型

```python
# 一次完整请求 = 1 个 trace，包含多个嵌套 span
Span:
  span_id: str
  trace_id: str            # 贯穿一次请求的所有 span
  parent_span_id: str|None # 构成调用树
  name: str                # "agent.react_agent" / "tool.hybrid_search" / "llm.deepseek.deepseek-chat"
  kind: str                # "agent" | "tool" | "llm"
  start_ms / end_ms
  status: "ok" | "error"
  attributes: dict         # tool 入参、LLM messages 数、finish_reason
  metrics: dict            # prompt_tokens / completion_tokens / cost_usd（仅 llm span）
```

`trace_id` 复用现有 `session_id` 关联规则，同一会话可串联。

### 2.2 TraceContext（协程安全的关键）

```python
# app/observability/trace.py（骨架）
import contextvars, time, uuid

_current_span: contextvars.ContextVar = contextvars.ContextVar("current_span", default=None)
_current_trace: contextvars.ContextVar = contextvars.ContextVar("current_trace", default=None)

class Span:
    def __init__(self, name, kind, trace_id, parent_span_id):
        self.span_id = uuid.uuid4().hex[:16]
        self.trace_id = trace_id
        self.parent_span_id = parent_span_id
        self.name, self.kind = name, kind
        self.start_ms = time.time() * 1000
        self.attributes, self.metrics = {}, {}
        self.status = "ok"

@contextmanager
def start_span(name: str, kind: str):
    parent = _current_span.get()
    trace_id = _current_trace.get() or uuid.uuid4().hex
    span = Span(name, kind, trace_id, parent.span_id if parent else None)
    token_s = _current_span.set(span)
    token_t = _current_trace.set(trace_id)
    try:
        yield span
    except Exception as e:
        span.status = "error"; span.attributes["error"] = str(e)
        raise
    finally:
        span.end_ms = time.time() * 1000
        _current_span.reset(token_s); _current_trace.reset(token_t)
        get_exporter().export(span)   # 落库 / 发 Langfuse
```

> `contextvars` 在 `asyncio` 下每个 Task 独立传播，多智能体并发（M5）时子 Agent 的 span 不会串。这点比用 thread-local 或全局变量正确得多，是这套设计的技术亮点。

---

## 3. 三处埋点（全部在基类/服务层，不动业务）

### 3.1 Agent 层 —— `agent/base.py:run()`

在 `run()` 里包一层 span，`trace_id` 注入 `AgentContext.metadata`：

```python
async def run(self, db, user_id, input_data, session_id=None):
    with start_span(f"agent.{self.name}", kind="agent") as span:
        span.attributes["question"] = input_data.get("question", "")[:200]
        context = AgentContext(user_id=user_id, session_id=session_id or ...)
        context.metadata["trace_id"] = span.trace_id
        ...
        # 落库 AgentRun 时把 trace_id 一起写入（新增列）
```

### 3.2 Tool 层 —— `agent/base.py:_call_tool()`

```python
async def _call_tool(self, tool_name, tool_input, context):
    with start_span(f"tool.{tool_name}", kind="tool") as span:
        span.attributes["input"] = {k: v for k, v in tool_input.items()
                                    if k not in ("db", "user_id")}  # 脱敏
        tool = self.tool_registry.get_tool(tool_name)
        result = await tool.execute(**tool_input)
        span.attributes["success"] = getattr(result, "success", None)
        context.add_action(tool_name, tool_input, result)
        return result
```

### 3.3 LLM 层 —— `llm_answer_service.py`（最有价值的埋点）

在 `_chat_completion` / `_chat_completion_raw` 内，包 span 并**抓取被丢弃的 `usage`**：

```python
def _chat_completion_raw(self, *, messages, tools=None, provider_class="routing"):
    base_url, api_key, model = self._resolve_endpoint(...)
    with start_span(f"llm.{self._active_provider()}.{model}", kind="llm") as span:
        span.attributes["messages_count"] = len(messages)
        span.attributes["has_tools"] = bool(tools)
        data = ...  # urlopen
        usage = data.get("usage") or {}
        span.metrics["prompt_tokens"] = usage.get("prompt_tokens", 0)
        span.metrics["completion_tokens"] = usage.get("completion_tokens", 0)
        span.metrics["cost_usd"] = estimate_cost(model, usage)  # M3 接入价格表
        span.attributes["finish_reason"] = (data.get("choices") or [{}])[0].get("finish_reason")
        return data
```

---

## 4. 导出器：默认落库，可选 Langfuse

```python
# exporters.py
class DBExporter:      # 默认，无外部依赖
    def export(self, span): 写入 trace_spans 表（新表）

class LangfuseExporter: # 可选，settings.langfuse_enabled=True 时启用
    def export(self, span): langfuse SDK 上报，本地 UI 可视化调用树

class NoopExporter:    # 测试/关闭观测时
    def export(self, span): pass
```

新表 `trace_spans`（沿用 `agent_runs` 的 sqlite/pg 双写法，加进 `bootstrap.apply_local_schema_fixes()`）：

```sql
CREATE TABLE trace_spans (
    span_id VARCHAR(32) PRIMARY KEY,
    trace_id VARCHAR(32) NOT NULL,
    parent_span_id VARCHAR(32),
    name VARCHAR(128), kind VARCHAR(16),
    start_ms BIGINT, end_ms BIGINT, duration_ms INTEGER,
    status VARCHAR(16),
    attributes JSON, metrics JSON,
    user_id UUID, session_id VARCHAR(64),
    created_at DATETIME NOT NULL
);
CREATE INDEX ix_trace_spans_trace_id ON trace_spans (trace_id);
```

`AgentRun` 新增 `trace_id` 列，把已有轨迹和新 span 树关联起来。

---

## 5. 可视化端点

新增 `GET /api/v1/observability/traces/{trace_id}`，返回 span 树 JSON，前端渲染成火焰图/调用树（复用现有前端框架，MVP 阶段可先只出 JSON）。

```
trace abc123 (总耗时 3200ms)
├─ agent.react_agent           3200ms
│  ├─ llm.xiaomi.mimo-v2.5       420ms  [routing 判定]
│  ├─ tool.hybrid_search         180ms
│  ├─ llm.deepseek.deepseek-chat 1900ms [prompt=1200 completion=350 tok, $0.0012]
│  └─ llm.deepseek.deepseek-chat  700ms [生成最终答案]
```

---

## 6. 验证方式

1. 单测：`start_span` 嵌套后 `parent_span_id` 正确构树；异常时 `status=error`
2. 单测：`contextvars` 在 `asyncio.gather` 并发下 span 不串（模拟两个并发 agent run）
3. 集成：真实跑一次 slow 问答，查 `trace_spans` 表有 agent/tool/llm 三类 span
4. 集成：LLM span 的 `prompt_tokens` > 0（证明 usage 抓取成功）
5. 回归：关闭观测（`NoopExporter`）时问答结果与改造前完全一致

---

## 7. 交付物

- `app/observability/` 模块（trace/exporters/decorators）
- `agent/base.py`、`llm_answer_service.py` 埋点改动
- `trace_spans` 表 + `AgentRun.trace_id` 列
- `GET /observability/traces/{trace_id}` 端点
- 单测 + 集成测试
- `infra_docs/results/M1_*.md` 实测数据（span 数、埋点开销 ms）
