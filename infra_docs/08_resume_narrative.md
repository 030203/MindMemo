# 简历话术与面试锚点（Resume Narrative）

> 本文把 6 个 Milestone 的工作翻译成**简历条目**和**面试可展开的技术故事**。
> 原则：每条都能被追问、都有真实代码支撑、都有可量化口径。不吹不存在的东西。

---

## 一、一句话定位（简历项目标题行）

> **MindMemo — 纯手写（无 LangChain）的个人记忆 Agent 系统与 LLM 基础设施**
> 独立设计并实现 Agent / Tool / Memory 三层解耦架构、两级意图路由、ReAct 与多智能体编排，并自建 LLM 网关、全链路可观测、成本计量、语义缓存与自动化评估闭环。

**为什么这样定位**：面试官一眼能看到两个层次——上层是 Agent 应用（会做 agent 的人多），下层是 LLM Infra（会做 infra 的人少、更值钱）。你两块都真做了。

---

## 二、简历条目（STAR 精简版，可直接粘贴）

> 数字用 `XX` 占位，M1–M5 落地后用真实 benchmark 填。宁可少写一个数字，也不编。

### 架构与编排
- 从零实现**无框架依赖**的 Agent 运行时（`BaseAgent` 模板方法 + `AgentContext` 轨迹记录），支持 ReAct 多轮推理、Plan 引导、Multi-Agent 协作三种执行模式，规避 LangChain 黑盒、全链路可调试。
- 设计**两级意图路由**（Router 快慢分流 → SlowRouter 判定 react/plan/multi_agent），用一次轻量 LLM 调用把请求导向最低成本的执行路径，失败自动降级到默认 ReAct。
- 用 **Agent-as-Tool** 模式实现多智能体：将「创建子 Agent」封装为工具（`create_sub_agent`），Coordinator 通过工具调用动态扇出子任务，权限随工具参数下发，代码层强制禁止子 Agent 再嵌套（防无限递归）。

### LLM 基础设施（改造重点）
- 自建 **LLM 网关**：在多 Provider（小米 MiMo / DeepSeek）之上实现故障转移、指数退避重试、超时熔断与多 Key 轮询，可用性从单点提升到多路冗余。
- 基于已持久化的 **Agent 轨迹**（`agent_runs` 表）构建**全链路可观测**：一次请求经过的 Router → SlowRouter → ReAct 每轮 → Tool 调用与 LLM 调用全部落为 span，接入 OpenTelemetry / Langfuse，支持轨迹回放。
- 实现按 user/session 维度的 **Token 与成本计量**，落库 + Prometheus 指标，可回答"哪类问题最烧钱"，并支持预算护栏。
- 设计**两级缓存**（精确缓存 + 基于 embedding 的语义缓存），复用现有向量能力，重复/近似问答命中缓存直接返回，降低 LLM 调用量 XX%。

### 质量与工程化
- 搭建 **Agent 评估闭环**：金标准数据集 + 自动打分（路由准确率 / 回答质量 / 工具选择正确性），改 prompt / 换模型前后自动回归，防止能力退化。
- 将 AI 增强、洞察生成、记忆维护等重活迁移到 **Celery + Redis 异步管线**，写路径 P95 延迟下降 XX%，并设计 EAGER 降级保证本地零外部依赖。

---

## 三、面试深挖故事（每个都是一个 5 分钟技术叙事）

### 故事 1：「为什么不用 LangChain？」
**这是你最大的差异化武器。** 大多数候选人只会 `import langchain`。你可以讲：
- LangChain 的 ReAct / Memory 是黑盒，出错难定位、prompt 难控、版本升级易碎。
- 你手写了 `BaseAgent` 的模板方法生命周期、ReAct 主循环（`react_agent.py` 的 `MAX_ROUNDS` 保护、Thought/Action/Observation 追加到 messages 链）、Tool 的 JSON Schema 自描述。
- 收益：每一步都能打点、能回放、能单测；这也正是后面能做「全链路可观测」的前提——**因为链路是你自己的**。

**可展开的深度**：`AgentContext.add_thought/add_action` 如何积累 trajectory，`run()` 如何在生命周期末尾把它持久化到 `agent_runs`。

### 故事 2：「两级路由怎么设计的？」
- 一级 Router：fast（单轮问答/闲聊）vs slow（多步分析）。fast 只挂 weather/web_search 外部工具白名单，不碰用户记录。
- 二级 SlowRouter：react（探索式，默认）/ plan（可预拆解，Planner 生成建议步骤注入 system prompt）/ multi_agent（重型报告，扇出子 Agent）。
- **痛点驱动落地**：先全走 ReAct，看到「乱逛/步数爆炸」再上 Plan，重型任务才上 Multi-Agent——不预先过度设计。这句话面试官会很买账。

### 故事 3：「LLM 调用怎么保证可靠性？」（改造后才能讲满）
- 现状诚实版：目前 `llm_answer_service` 是 urllib 手写，有多 Provider 路由 + 多 Key 轮询，但**重试/熔断缺失**。
- 改造版：抽出 `LLMGateway`，加 tenacity 指数退避、Provider 故障转移（MiMo 挂了转 DeepSeek）、超时熔断、每次调用记录 token/latency/cost。
- 亮点：**内部任务与用户可见回答走不同 Provider**（routing 用便宜快的，user_facing 用质量好的）——这是成本/质量权衡的真实工程决策。

### 故事 4：「多智能体的权限和递归怎么控制？」
- Agent-as-Tool：Coordinator 是个 ReActAgent，通过调 `create_sub_agent` 工具创建子 Agent，子 Agent 的工具权限由调用参数 `allowed_tools` 决定。
- 硬约束：子 Agent 的工具集**代码层强制过滤掉 `create_sub_agent`**，深度锁死为 1，杜绝无限嵌套。子 Agent MAX_ROUNDS=5 比顶层的 10 更保守。
- `mailbox` 做子 Agent 结果收集，`collect_results` 工具聚合。

### 故事 5：「怎么知道你的 Agent 没变差？」
- 评估闭环：金标准数据集（路由标签 / 期望工具 / 参考答案）+ 自动打分。
- 用 `agent_runs` 表做**轨迹回放**：线上真实 case 沉淀成回归集。
- 每次改动跑 eval，路由准确率 / 工具选择正确率 / 答案相关性作为门禁。

---

## 四、量化口径清单（落地后填数字）

| 指标 | 采集方式 | 出现在哪个 Milestone |
|------|---------|---------------------|
| LLM 调用成功率 / 重试率 | LLM 网关埋点 | M2 |
| P95 端到端延迟 | tracing span 汇总 | M1 |
| 缓存命中率 / LLM 调用量下降 % | 缓存层计数 | M4 |
| 单次问答平均 token / 成本 | 成本计量落库 | M3 |
| 路由准确率 / 工具选择正确率 | eval harness | M5 |
| 写路径 P95 延迟下降 % | 异步化前后对比 | M6 |

> **采数方法**：M1 完成后先跑一批真实问答做 baseline，每个 Milestone 完成再测一次，用对比数字。这样每个数字都有出处，面试问「怎么测的」你答得出。

---

## 五、忌讳（别踩雷）

- ❌ 别写「精通 LangChain」——你恰恰是**不用**它，讲反了浪费最大亮点。
- ❌ 别编 QPS / 用户量——个人项目吹并发一问就穿。要吹就吹**架构设计**和**工程严谨性**。
- ❌ 别把「计划要做」写成「已经做完」。M1–M6 做一个填一个，简历只写已完成的。
- ✅ 强调**独立设计 + 从零实现 + 可解释的技术选型**，这是个人项目的真正价值。
