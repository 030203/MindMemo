# MindMemo Agent Infra 改造总纲

**版本**: v1.0
**日期**: 2026-07-06
**定位**: 把 MindMemo 已有的手写 Agent 内核，升级为一套**生产级、可观测、可评估、有成本护栏的 LLM Agent 基础设施**。
**核心判断**: 不推倒重来。MindMemo 已经拥有 Agent/Tool/Memory 三层解耦、两级路由、ReAct/Plan/Multi-Agent 三条执行路径、以及 `AgentRun` 轨迹持久化。缺的不是"框架"，而是让这套框架"能上线、看得见、算得清、退不了化"的一层 infra。

---

## 0. 现状盘点（基于真实代码，不是文档）

> 下面每一条都对应仓库里的实际文件，改造计划全部围绕这些真实资产展开。

### 0.1 已有资产（要保护和放大的）

| 资产 | 位置 | 说明 |
|------|------|------|
| Agent 基类 + 执行上下文 | `backend/app/agent/base.py` | `BaseAgent` 模板方法（run→pre→execute→post），`AgentContext` 记录 `trajectory` / `tool_calls` / `variables` |
| 轨迹持久化 | `backend/app/models/agent_run.py` | `AgentRun` 表已落库 trajectory/tool_calls/duration_ms/status —— **tracing 与轨迹评估的现成地基** |
| 两级路由 | `orchestration/router.py` + `slow_router.py` | 一级 fast/slow，二级 react/plan/multi_agent。轻量 LLM 判定 + 规则兜底 |
| ReAct 引擎 | `agent/react_agent.py` | Thought→Action→Observation 主循环，MAX_ROUNDS 保护，来源引用抽取 |
| Agent-as-Tool 多智能体 | `tools/agent/{create_sub_agent,collect_results,mailbox}.py` | 「创建子 Agent」本身是一个 Tool，权限内嵌在工具参数里，深度硬约束防无限嵌套 |
| 多 Provider LLM 层 | `services/llm_answer_service.py` | 小米 MiMo（内部任务）/ DeepSeek（用户可见）双 provider 路由 + 多 key 轮询 + 流式 + function calling |
| 工具系统 | `tools/registry.py` + `tools/base.py` | ToolRegistry 单例，BaseTool 自描述 JSON Schema，8 个已注册工具 |
| 分层记忆 | `memory/manager.py` + `memory/layers/*` | Working/Episodic/Semantic/Goal/Procedural/Insight 六层，门面模式 |

### 0.2 关键缺口（infra 化要补的）

> 这些缺口是"demo 能跑"与"生产能扛"之间的差距。每一个都在下面的改造项里有对应。

| # | 缺口 | 现状证据 | 影响 |
|---|------|---------|------|
| G1 | **无分布式 tracing** | `AgentContext.trajectory` 只存进 DB，没有 span/耗时分解，没导出到任何观测系统 | 一次多轮 ReAct 出错无法定位是哪一步、哪个工具、哪次 LLM 调用 |
| G2 | **无 token / 成本计量** | `llm_answer_service` 每次调用丢弃了 response 里的 `usage` 字段 | 不知道每个用户/每类问题烧了多少钱，无法做预算 |
| G3 | **无重试 / 故障转移 / 熔断** | `_chat_completion` 一次 `urlopen`，抛错即失败；provider 之间不会互相兜底 | 单 provider 抽风 → 整条链路挂 |
| G4 | **无缓存** | 相同问题每次都全量走 LLM + 全量 ReAct | 成本浪费、延迟高 |
| G5 | **评估零散** | `tests/eval/*` 是一次性脚本，无金标准集、无回归门禁 | 改 prompt/模型后无法判断是否退化 |
| G6 | **死代码误导** | `llm/client.py` 用了已废弃的 `openai.error`，实际没被 agent 链路使用 | 维护者容易改错地方 |
| G7 | **无并发扇出** | Multi-Agent 的 `collect_results` 目前是顺序执行子 agent | 月报类重型任务延迟叠加 |
| G8 | **无统一配额 / 限流** | 无按用户维度的调用频次、预算上限 | 无法多租户、易被刷爆 |

### 0.3 一句话战略

> **把 `AgentContext` 从"临时日志对象"升级为"可观测执行单元"，把 `llm_answer_service` 从"能调通的裸客户端"升级为"有护栏的 LLM 网关"，再用这两者的产出喂给一套自动评估闭环。** 三件事做完，MindMemo 就从"作品"变成"系统"。

---

## 1. 目标架构（改造后）

```
                         ┌──────────────────────────────────────────┐
                         │        Observability Plane (新增)         │
                         │  Tracer(OTel/Langfuse) · CostMeter ·      │
                         │  MetricsExporter · TraceReplay            │
                         └──────────────────────────────────────────┘
                              ▲ span      ▲ token/cost   ▲ 轨迹
                              │           │              │
┌──────────────┐   ┌─────────┴───────────┴──────────────┴──────────┐
│  API / 前端  │──▶│              Orchestration (已有, 埋点增强)      │
└──────────────┘   │  Router → SlowRouter → ReAct/Plan/Multi-Agent  │
                   └─────────┬──────────────────────────────────────┘
                             │ 每个 Agent/Tool/LLM 调用都被 span 包裹
                   ┌─────────▼──────────────────────────────────────┐
                   │            LLM Gateway (新增, 包住旧服务)        │
                   │  重试 · 多provider故障转移 · 熔断 · 超时 ·       │
                   │  语义+精确缓存 · token计量 · 限流/配额           │
                   │        └── 底层仍是 llm_answer_service          │
                   └─────────┬──────────────────────────────────────┘
                             │
                   ┌─────────▼──────────┐   ┌────────────────────────┐
                   │   Tool Registry    │   │   Evaluation Harness    │
                   │  (已有 + 并发扇出) │   │  金标准集 · 自动打分 ·  │
                   └────────────────────┘   │  回归门禁 · 轨迹重放     │
                                            └────────────────────────┘
```

**设计原则**：所有新增能力以**装饰器/包裹层**形式接入，不改动 Agent 与 Tool 的业务逻辑。旧代码零重写，新能力可开关（feature flag）。

---

## 2. 改造分期（6 个 Milestone，约 6~8 周）

> 排序原则：**先建"眼睛"（可观测），再建"护栏"（可靠性 + 成本），最后建"防退化"（评估）**。每个 Milestone 独立可交付、可验证、可写进简历。

| MS | 名称 | 核心产出 | 依赖 | 预计 | 详细设计 |
|----|------|---------|------|------|---------|
| **M1** | 全链路可观测 | Tracer + Agent/Tool/LLM 三级 span 埋点 + 轨迹回放 | 无 | Week 1-2 | `02_M1_observability.md` |
| **M2** | LLM 网关 · 容错 | LLMGateway：重试/多 provider 故障转移/熔断/超时分级 | M1 | Week 2-3 | `03_M2_llm_gateway.md` |
| **M3** | Token / 成本计量 | 按用户/会话/任务类型的 token&成本核算 + 预算熔断 | M2 | Week 3-4 | `04_M3_cost_metering.md` |
| **M4** | 语义缓存层 | 精确缓存 + 语义缓存（复用 embedding） | M2 | Week 4-5 | `05_M4_semantic_cache.md` |
| **M5** | 评估闭环 | 金标准集 + 自动打分 + CI 回归门禁 + 轨迹重放 | M1 | Week 5-6 | `06_M5_eval_harness.md` |
| **M6** | 异步链路上队列 | Insight/Memory Manager 队列驱动、可重试、可观测 | M1 | Week 6-8 | `07_M6_async_pipeline.md` |

每个 Milestone 的详细设计见上表对应文档；Multi-Agent 并发扇出与用户级限流/配额作为 M2、M6 的延伸项在各自文档内说明。

---

## 3. 创新点（简历里可写、面试可讲）

> 创新点不是硬造，而是从你已有的独特设计里提炼、再补一层 infra 把它做扎实。

### 创新点 1：**统一执行上下文驱动的全链路可观测（Context-Native Tracing）**
- **是什么**：不引入重型 APM，而是把已有的 `AgentContext` 扩展成"自带 span 树"的执行单元。Agent、Tool、LLM 三级调用自动生成父子 span，`trajectory` 直接映射为 trace，落进 `AgentRun` 的同时导出到 Langfuse/OTel。
- **为什么是创新**：多数教程级 agent 项目要么没观测，要么硬塞 LangSmith。这里是**用业务已有的上下文对象做零侵入 tracing**，trace 与业务轨迹天然同构，还能"轨迹重放"复现线上问题。
- **简历话术**：设计并实现基于执行上下文的全链路 tracing，将 Agent/Tool/LLM 三级调用建模为 span 树，支持线上多轮推理的耗时分解与轨迹回放。

### 创新点 2：**双 Provider 智能路由 + 成本感知的 LLM 网关**
- **是什么**：在已有"内部任务走 MiMo / 用户可见走 DeepSeek"的 provider 分级之上，加一层网关，统一做重试、跨 provider 故障转移、熔断、token/成本核算。让"用便宜模型做路由判定、用强模型做终答"这件事**变成可度量、可容错的基础设施**。
- **为什么是创新**：把"模型分级"从散落在代码里的 if-else，升级成一个有 SLA（超时/重试/降级）和成本账本的网关组件。
- **简历话术**：实现成本感知的 LLM 网关，支持多 Provider 按任务类型路由、失败自动降级与熔断，并按用户/会话维度核算 token 与成本。

### 创新点 3：**Agent-as-Tool 的可观测多智能体编排**
- **是什么**：你已有的"创建子 Agent 是一个 Tool"设计（`create_sub_agent` + `mailbox` + 深度硬约束）本身就很有辨识度。infra 化补上：子 Agent 的并发扇出 + 每个子 Agent 独立 span + 子任务 token 归集到父任务。
- **为什么是创新**：业界多智能体大多硬编码 DAG。这里是**让 Coordinator 用工具调用动态决定何时/如何派生子 Agent，权限内嵌于工具参数，且全程可观测**。
- **简历话术**：设计 Agent-as-Tool 的多智能体协作机制，Coordinator 通过工具调用动态派生受限子 Agent（权限内嵌、深度硬约束防递归），支持并发扇出与子任务级成本归集。

### 创新点 4：**轨迹回放驱动的离线评估（Trajectory-Replay Eval）**
- **是什么**：利用 `AgentRun` 已持久化的完整 trajectory，构建"金标准问答集 + 自动打分 + 回归门禁"。不仅评最终答案，还能**基于轨迹评"工具选择是否正确、路由是否合理"**。
- **为什么是创新**：普通 eval 只看最终输出；这里能对中间决策（路由/工具选择）单独打分，定位退化发生在哪一层。
- **简历话术**：构建基于执行轨迹回放的离线评估体系，对路由准确率、工具选择正确率、终答质量分层打分，接入 CI 作为 prompt/模型变更的回归门禁。

---

## 4. 可度量的成功指标（改造前后对比，简历用数字）

> 落地时把这些指标填进 `04_metrics_baseline.md`，改造前后各测一次，简历里就是硬数字。

| 维度 | 指标 | 采集方式 |
|------|------|---------|
| 可观测 | 单请求可定位到 span 级（耗时分解覆盖率 100%） | M1 后从 trace 统计 |
| 成本 | 每千次问答 token 消耗、估算成本；缓存命中后的成本下降 % | CostMeter |
| 延迟 | fast/slow 各路径 P50/P95 延迟；缓存命中路径延迟 | Tracer |
| 可靠性 | LLM 调用成功率（重试+故障转移前后对比）、熔断触发次数 | Gateway 指标 |
| 缓存 | 精确/语义缓存命中率 | 缓存层埋点 |
| 质量 | 路由准确率、工具选择正确率、终答通过率 | 评估闭环 |

---

## 5. 风险与边界

- **不做的事**：不抽象"通用 agent 框架对外发布"（只有一个使用方，过早抽象是负债）；不引入 LangChain（违背项目"纯手写可控"的既定原则）；不做真多租户鉴权体系（M5 只做用户级配额）。
- **兼容性**：所有改造走"包裹 + feature flag"，旧链路可随时回退。SQLite/PostgreSQL 双库要各测一遍（`bootstrap.py` 已有双库 DDL 分支）。
- **数据安全**：trace 与成本日志可能含用户记录内容，导出到外部观测系统时要脱敏（M1 处理）。
- **验证**：每个 Milestone 完成后跑全量回归（`backend/tests/`），并用真实 provider 做一次 E2E。

---

## 6. 文档地图

- `README.md` — 索引
- `00_master_plan.md` — 本文（总纲：现状、架构、分期、创新点、指标）
- `01_current_architecture.md` — 现状架构详解（数据流、真实调用链、埋点位置）
- `02_M1_observability.md` — M1 全链路可观测
- `03_M2_llm_gateway.md` — M2 LLM 网关（重试/故障转移/熔断）
- `04_M3_cost_metering.md` — M3 Token / 成本计量与预算
- `05_M4_semantic_cache.md` — M4 语义缓存层
- `06_M5_eval_harness.md` — M5 评估闭环
- `07_M6_async_pipeline.md` — M6 异步链路上队列
- `08_resume_narrative.md` — 简历话术、面试深挖故事、量化口径
- `results/`（落地时创建）— 各 Milestone 的实测数据与指标基线

---

*本计划严格基于 2026-07-06 时的仓库实际代码编写。所有文件路径、类名、缺口均已核对。*
