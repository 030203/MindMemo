# 现状架构详解（改造前）

> 基于 2026-07-06 仓库实际代码。这份文档是改造的"before"快照，读懂它才能理解每个 Milestone 改的是哪一环。

## 1. 一次问答的真实调用链

以用户在对话框输入「我上周记了哪些跟 Python 相关的东西」为例：

```
POST /api/v1/chat (chat.py)
  └─ qa_service / qa_workflow.run(question, history, user_id, db)   [orchestration/qa_workflow.py]
       │
       ├─ Router.route(q)                        [orchestration/router.py]
       │     规则优先 + 轻量 LLM 判定 → RouterResult(fast|slow)
       │
       ├─ [fast] _handle_fast_with_tools()
       │     携带 weather + web_search，最多 3 轮 function_call 小循环
       │     └─ llm_answer_service.function_call(messages, tools)
       │
       └─ [slow] _handle_slow()
             ├─ SlowRouter.route(q, memory_context)  [orchestration/slow_router.py]
             │     轻量 LLM 判定 → react | plan | multi_agent（失败降级 react）
             │
             ├─ [react]  ReActAgent.run(db, user_id, input_data)   [agent/react_agent.py]
             │     BaseAgent.run → _pre_execute（加载记忆）→ execute（ReAct 主循环）→ _post_execute
             │     主循环: llm_answer_service.function_call → _call_tool → 追加 observation → 循环
             │     结束: 落库 AgentRun(trajectory, tool_calls, duration_ms)
             │
             ├─ [plan]   Planner.create_plan() 生成步骤 → 注入 ReActAgent 的 system prompt
             │
             └─ [multi]  _build_coordinator()：ReActAgent + create_sub_agent + collect_results
                   子 Agent 通过 mailbox 通信，顺序执行后 collect_results 归集
```

## 2. 三层调用的真实入口（埋点位置预判）

改造的所有 span 埋点，都落在这三个"咽喉"上：

| 层 | 真实入口方法 | 文件 | 埋点后产出的 span |
|----|-------------|------|------------------|
| **Agent 层** | `BaseAgent.run()` | `agent/base.py:155` | `agent.{name}` 根/子 span，已有 duration_ms |
| **Tool 层** | `BaseAgent._call_tool()` | `agent/base.py:283` | `tool.{tool_name}` span，已记 add_action |
| **LLM 层** | `LLMAnswerService._chat_completion` / `_chat_completion_raw` / `chat_stream` | `services/llm_answer_service.py:327 / 269 / 400` | `llm.{provider}.{model}` span + token/cost |

> 关键：这三个方法是**唯二真正发起副作用的地方**。只要包住它们，全链路可观测就成立，无需改任何业务 Agent。

## 3. LLM 层现状（重点，M2/M3 的改造对象）

`llm_answer_service.py` 是真正在跑的 LLM 层（`llm/client.py` 是死代码，用了废弃的 `openai.error`）。

**已有能力**：
- 双 provider 路由：`_resolve_endpoint(provider_class=)`，`routing` 类走小米 MiMo，`user_facing` 类走 DeepSeek
- 小米多 key 轮询：`_next_xiaomi_key()`，线程安全 `itertools.cycle`
- 四种调用形态：`chat` / `chat_with_system` / `parse_json` / `function_call` / `chat_stream`
- 底层统一走 `urllib.request`（无第三方 HTTP 依赖）

**缺口**（M2/M3 补）：
- 每次 `urlopen` 只调一次，`HTTPError` 直接抛出 —— 无重试、无退避
- provider 之间不互相兜底 —— MiMo 挂了不会切 DeepSeek
- response 里的 `usage`（prompt_tokens/completion_tokens）被丢弃 —— 无计量
- 无缓存 —— 相同 prompt 重复烧钱
- 无熔断 —— provider 持续失败仍反复打

## 4. 轨迹持久化现状（M1/M4 的地基）

`AgentRun` 表（`models/agent_run.py`）已落库：`trajectory`、`tool_calls`、`run_metadata`、`duration_ms`、`status`。在 `BaseAgent.run()` 结尾写入（`base.py:212`）。

**已有**：完整的 thought/action/observation 轨迹（JSON）。
**缺**：
- 无 span 级耗时（只有整个 run 的 duration_ms，不知道每个 tool/LLM 各花多久）
- 无 token/cost 字段
- 无 trace_id 关联同一会话的多次 run
- 未导出到任何可查询/可视化的观测系统

## 5. 工具系统现状

`ToolRegistry` 单例（`tools/registry.py`），`bootstrap.py:initialize_tools()` 注册 8 个工具：
`hybrid_search` / `read_memory` / `list_tasks` / `time_resolver` / `fact_extractor` / `relation_finder` / `web_search` / `weather`。

多智能体专用工具（`tools/agent/`）：`create_sub_agent` / `collect_results` / `mailbox`，不注册进全局，由 `_build_coordinator()` 动态组装。

`collect_results` 当前**顺序**执行子 Agent —— M5 改并发。

## 6. 配置现状（`core/config.py`）

- `llm_provider` / `llm_user_facing_provider`：provider 分级开关
- `xiaomi_*`（base_url/model/多 key）、`openai_*`（DeepSeek 复用）
- `tavily_api_key`（web_search）、`openweather_api_key`（weather）
- `llm_request_timeout_seconds`、`llm_max_completion_tokens`
- 默认 SQLite，支持 PostgreSQL（`docker-compose.pgvector.yml`）

新增配置（各 Milestone）统一加在这里，走 `pydantic-settings`，保持可通过 `.env` 覆盖。
