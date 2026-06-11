# AI Agent 长期演进路线图（Phase 7-16）

## 定位重申

MySecondBrain 不是普通待办、记事本或后台系统，而是一个长期演进的 **AI Native Personal Memory & Workflow System**。

核心产品目标：

1. 用户可以用极低成本随手输入任何信息。
2. 系统能把非结构化输入理解为长期可用的个人记忆资产。
3. Agent 能基于记忆完成检索、归纳、推理、总结、提醒和工作流编排。
4. 所有 AI 结论必须尽量可追溯、可解释、可校正。

核心设计原则：

- 原始记忆永远保留，结构化事实、摘要、画像和洞察都是派生层。
- AI 可以建议和生成候选项，但不能无授权修改用户核心数据。
- Retrieval 质量、Evaluation、Workflow 可观测性优先于堆叠新页面。
- UI 是 AI 工作流的一部分，不是装饰层；必须保持克制、沉浸、可理解。

## 当前阶段基线

Phase 0-6 已完成 MVP 可验收闭环：

- 数据持久化
- 用户鉴权
- 基础 RAG
- URL / PDF 摄取
- 提醒与通知
- Review Queue
- Phase 6 smoke test
- 深色 AI SaaS 工作台视觉体系

后续进入 Phase 7-16：从“能记录、能检索”升级到“能理解、能推理、能长期记忆、能主动协作”。

## 阶段总览

| 阶段 | 名称 | 主要风险点 | 核心产出 |
|---|---|---|---|
| Phase 7 | Memory Intelligence Layer | 非结构化输入理解质量 | 自动分类、结构化抽取、置信度与 Review |
| Phase 8 | Structured Facts & Temporal Index | 个人事实数据模型 | Expense / Mood / Plan / Learning Fact 与时间索引 |
| Phase 9 | Retrieval Evaluation Harness | RAG 改进不可衡量 | Golden dataset、召回评估、答案评估、Tracing |
| Phase 10 | Hybrid Retrieval & Memory Graph | 复杂问题召回不准 | Hybrid search、metadata filter、关系边 |
| Phase 11 | Agentic RAG Workflow | 单步 QA 无法处理复杂问题 | Query planning、tool routing、context packing |
| Phase 12 | Personal Insight Agents | 只回答不分析 | 消费、情绪、学习、项目洞察 Agent |
| Phase 13 | Long-term Memory & Reflection | 长期上下文失控 | 日/周/月总结、记忆压缩、个人画像 |
| Phase 14 | Proactive Workflow System | 系统缺少主动性 | Daily Digest、风险提醒、主动复盘 |
| Phase 15 | Multi-Agent Orchestration | 多 Agent 难观测难调优 | Agent 调度、状态机、workflow tracing |
| Phase 16 | Personal OS Productization | 产品化、隐私、稳定性 | 权限、导出、部署、性能、体验验收 |

---

## Phase 7：Memory Intelligence Layer

### 核心目标

让系统能理解用户随手输入的一句话，并将其转化为可检索、可推理、可校正的记忆对象。

### 必须实现

- 输入理解 pipeline：
  - 自动分类：memo / expense / mood / health / learning / plan / todo_candidate / relationship / project
  - 自动标签
  - 自动摘要
  - 实体抽取：人、地点、物品、项目、技术、金额、时间
  - 时间表达解析：今天、昨天、下个月、上周、具体日期
  - 置信度评分
- 新增 `ExtractedFact` 基础模型：
  - `fact_type`
  - `structured_payload`
  - `confidence_score`
  - `source_memory_id`
  - `event_time`
- 低置信度抽取进入 Review Queue。
- Memory Detail 页面展示 AI 抽取结果与置信度。

### 技术重点

- Prompt versioning
- Pydantic schema validation
- Extractor service
- 可重跑的 fact extraction pipeline
- 错误与低置信度兜底

### UI/UX 重点

- Memory Detail 增加“AI 理解结果”区域。
- Review Queue 显示“为什么需要确认”与“AI 建议怎么理解”。
- Capture 仍保持低摩擦，不要求用户手动填复杂字段。

### 先不做

- 完整财务账本
- 情绪心理报告
- GraphRAG
- 自动创建大量任务

### 退出条件

- 输入“今天花了100元买耳机”能抽取 expense fact。
- 输入“昨天晚上睡得不好”能抽取 mood / health fact。
- 输入“下个月记得交房租”能识别 plan / todo_candidate。
- 抽取结果能在详情页看到，并可进入 Review Queue。

---

## Phase 8：Structured Facts & Temporal Index

### 核心目标

建立面向 Agent 推理的结构化事实层和时间索引，让系统能回答聚合类问题。

### 必须实现

- 扩展 `ExtractedFact`：
  - expense schema：金额、币种、品类、商户/对象、支付时间
  - mood schema：情绪、强度、触发因素、时间
  - learning schema：主题、技术、材料、进展
  - plan schema：截止时间、提醒时间、相关对象
- 新增 temporal index 字段：
  - `event_date`
  - `event_month`
  - `event_week`
  - timezone normalized time
- 支持事实聚合 API：
  - 月度消费汇总
  - 时间范围内情绪记录
  - 最近学习主题
- 支持从原始 memory 回溯到 fact。

### 技术重点

- 时间归一化
- 结构化 JSON 查询
- PostgreSQL JSONB / SQLite 兼容策略
- 事实重建脚本

### UI/UX 重点

- Memory Feed 增加轻量 fact chip。
- 首页增加非侵入式洞察卡，不做复杂 dashboard。
- Timeline 以事件为核心，而不是列表堆叠。

### 先不做

- 图表大屏
- 复杂预算系统
- 医疗级情绪判断

### 退出条件

- 能基于结构化 facts 回答“这个月总共花了多少钱？”
- 能列出“最近睡眠/情绪相关记录”。
- 能按月份筛选 facts。

---

## Phase 9：Retrieval Evaluation Harness

### 核心目标

建立 RAG 质量评估体系，让后续检索优化可以被量化，而不是靠感觉。

### 必须实现

- Golden dataset：
  - 30-50 条种子记忆
  - 20-30 个固定问题
  - 标注期望命中的 memory / fact
- Retrieval eval：
  - Recall@k
  - MRR
  - citation hit rate
  - temporal filter accuracy
- Answer eval：
  - 是否引用来源
  - 是否遗漏关键事实
  - 是否产生无来源结论
- 新增 eval 脚本：
  - `scripts/eval_retrieval.py`
  - `scripts/eval_qa_grounding.py`
- 每次 retrieval 记录 trace：
  - query
  - rewritten query
  - filters
  - candidates
  - selected context

### 技术重点

- Harness 工程
- 可重复数据集
- eval report
- retrieval trace storage

### UI/UX 重点

- 不面向普通用户暴露复杂指标。
- 可在开发模式提供 lightweight debug panel。

### 先不做

- 自动化 LLM-as-judge 作为唯一评估标准
- 大规模评测平台

### 退出条件

- 能一键跑 retrieval regression。
- 每次 RAG 改动能比较质量是否变好。
- 能定位“没搜到”还是“搜到了但没用好”。

---

## Phase 10：Hybrid Retrieval & Memory Graph

### 核心目标

提升复杂问题的召回质量，从简单向量检索升级为 hybrid retrieval 和轻量关系图。

### 必须实现

- Hybrid Search：
  - vector similarity
  - keyword / BM25-like search
  - metadata filter
  - time filter
  - fact filter
- Rerank v1：
  - query-memory relevance
  - recency
  - importance
  - confidence
- Memory Relation v1：
  - same entity
  - same topic
  - temporal adjacency
  - source-derived relation
- 支持问题类型路由：
  - semantic recall
  - temporal aggregation
  - structured fact query

### 技术重点

- Query analyzer
- Retrieval strategy router
- Relation builder
- Index rebuild command
- 检索结果去重与 context packing

### UI/UX 重点

- Memory Detail 展示“相关记忆”。
- QA 引用区显示来源类型：memory / fact / timeline。
- 不把 Memory Graph 做成复杂可视化大图。

### 先不做

- Neo4j
- 复杂 GraphRAG
- 花哨关系图谱 UI

### 退出条件

- “最近提到 RAG 架构的内容有哪些？”能命中语义相关记录。
- “上个月在哪方面花钱最多？”能走 fact 聚合而不是纯向量猜测。
- QA citations 中能同时引用 memory 和 fact。

---

## Phase 11：Agentic RAG Workflow

### 核心目标

让 QA 从“单次检索 + 回答”升级为 Agentic RAG：先判断意图，再规划检索与工具调用。

### 必须实现

- Query Intent Router：
  - recall
  - aggregation
  - timeline
  - expense
  - mood
  - planning
  - open chat
- Query Planner：
  - 子问题拆解
  - 时间范围识别
  - 所需工具选择
- Tool Calling：
  - search_memory
  - search_facts
  - aggregate_expense
  - query_timeline
  - fetch_related_memories
- Context Router：
  - 决定进入 LLM 的上下文
  - 控制 token budget
  - 保留 citation mapping
- Answer Verifier：
  - 检查无来源结论
  - 检查引用是否存在

### 技术重点

- Workflow state model
- Tool schema
- Prompt versioning
- Trace / observability
- failure fallback

### UI/UX 重点

- Chat 页面展示轻量 Agent Activity：
  - “正在检索记忆”
  - “正在聚合消费记录”
  - “正在整理引用”
- 用户不需要看到复杂链路，但要感到系统在认真工作。

### 先不做

- 多 Agent 自主循环
- 自动执行外部操作
- 无限制工具调用

### 退出条件

- 复杂问题可被拆解并调用不同 retrieval 工具。
- 答案中能说明“基于哪些记录/事实得出”。
- Agent trace 可供开发排查。

---

## Phase 12：Personal Insight Agents

### 核心目标

从“回答问题”升级为“主动形成个人洞察”。

### 必须实现

- Expense Analysis Agent：
  - 月度消费
  - 分类消费
  - 异常消费提示
- Mood / Health Reflection Agent：
  - 睡眠、情绪、压力趋势
  - 只做记录层面的反思，不做医疗判断
- Learning Agent：
  - 最近研究主题
  - 技术关键词趋势
  - 学习材料总结
- Project Agent：
  - 项目进展
  - 卡点
  - 未完成承诺
- Insight API：
  - `/insights/overview`
  - `/insights/expenses`
  - `/insights/reflection`

### 技术重点

- 聚合查询
- Insight cache
- 时间窗口
- 每个 Agent 独立 prompt 与 eval

### UI/UX 重点

- 首页增加“洞察卡片”。
- 不做复杂报表；用自然语言洞察 + 少量关键数字。
- 每条洞察可点击查看来源。

### 先不做

- 完整 BI dashboard
- 图表堆叠
- 心理诊断

### 退出条件

- 能回答并展示“本月消费概况”。
- 能总结“最近主要在研究哪些技术”。
- 洞察必须能回溯来源记录。

---

## Phase 13：Long-term Memory & Reflection

### 核心目标

构建长期记忆层，让系统从事件记忆成长为能理解用户长期模式的个人上下文系统。

### 必须实现

- Daily Summary：
  - 当日记录
  - 当日待办
  - 当日情绪/消费/学习摘要
- Weekly Review：
  - 主题变化
  - 重要事件
  - 未完成事项
- Monthly Memory Compression：
  - 将历史碎片压缩为长期摘要
  - 保留引用回链
- User Profile Memory：
  - 长期项目
  - 常见人物
  - 关注主题
  - 偏好与习惯
- Reflection Queue：
  - 需要用户确认的长期洞察进入 Review Queue

### 技术重点

- Summary job
- Memory compression
- Profile memory schema
- Source linking
- Conflict handling

### UI/UX 重点

- 新增 Review / Digest 体验，而不是复杂报告页。
- Timeline 支持日/周/月视图。
- 用户可以修正长期画像。

### 先不做

- 自动决定用户目标
- 自动修改长期画像
- 过度人格化

### 退出条件

- 系统能生成日总结和周总结。
- 用户可查看长期主题与来源。
- 长期摘要不会丢失原始引用链。

---

## Phase 14：Proactive Workflow System

### 核心目标

让系统具备温和主动性，帮助用户回顾、提醒、复盘，而不是被动等待提问。

### 必须实现

- Daily Digest Agent：
  - 今日记录摘要
  - 明日提醒
  - 风险事项
- Reminder Enhancement：
  - 从 plan / todo_candidate / due_time 中生成提醒候选
  - 需要授权的进入 Review Queue
- Risk Detector：
  - 临期未完成
  - 重复拖延
  - 大额消费
  - 情绪低落连续出现
- 通知策略：
  - in-app
  - PushDeer
  - Server酱
  - 企业微信
  - quiet hours
- 用户可控：
  - 关闭某类主动提醒
  - 调整频率

### 技术重点

- Background scheduler
- Notification policy
- Quiet hours
- Deduplication
- Failure retry

### UI/UX 重点

- 通知设置要清晰解释“会通知什么”。
- Digest 页面要像一封高质量 briefing，不像报表。
- 主动提醒必须克制，避免打扰。

### 先不做

- 高频打扰
- 自动外部执行
- 多渠道轰炸

### 退出条件

- 系统每天能生成 digest。
- 可基于结构化 facts 和 todos 生成主动提醒。
- 通知有去重、静默时段和用户偏好控制。

---

## Phase 15：Multi-Agent Orchestration

### 核心目标

将单 Agent 能力升级为可观测、可调度、可扩展的多 Agent Workflow。

### 必须实现

- Agent Registry：
  - Memory Retrieval Agent
  - Timeline Agent
  - Expense Agent
  - Reflection Agent
  - Summary Agent
  - Reminder Agent
- Workflow State：
  - input
  - plan
  - tool calls
  - intermediate result
  - final result
  - trace
- Orchestrator：
  - 根据 intent 选择 Agent
  - 控制调用顺序
  - 失败降级
  - 防止无限循环
- Observability：
  - Agent run log
  - tool latency
  - retrieval quality
  - prompt version

### 技术重点

- State machine
- Tool contracts
- Agent trace table
- Prompt registry
- Cost / latency tracking

### UI/UX 重点

- 面向用户展示简化版 Agent Activity。
- 面向开发者提供 Workflow Trace。
- 不把多 Agent 做成炫技界面。

### 先不做

- 自主无限循环 Agent
- 自动修改外部系统
- 未授权联网执行

### 退出条件

- 一个复杂问题能触发多 Agent 协同。
- 每次 Agent run 可追踪、可复盘、可调试。
- 失败时能优雅降级。

---

## Phase 16：Personal OS Productization

### 核心目标

把系统从个人原型推向可长期使用的 Personal OS 产品形态。

### 必须实现

- 安全与隐私：
  - refresh token 撤销
  - 设备会话管理
  - 数据导出
  - 数据删除
  - sensitive memory 标记
- 性能：
  - embedding cache
  - query cache
  - summary cache
  - background job queue
- 部署：
  - PostgreSQL / pgvector 部署说明
  - 数据备份
  - 环境变量检查
  - health / readiness endpoint
- 产品体验：
  - 完整 onboarding
  - empty state 教学
  - demo data reset
  - keyboard shortcuts
- 验收：
  - E2E smoke test
  - browser screenshot QA
  - RAG regression
  - notification regression

### 技术重点

- Security hardening
- Data portability
- Observability
- Deployment automation
- Test matrix

### UI/UX 重点

- 建立完整 Design Language 文档。
- 完成 Workspace / Memory Feed / Timeline / Chat / Review / Settings 的截图级验收。
- 支持桌面、平板、移动端稳定体验。

### 先不做

- 团队协作
- 企业权限体系
- 移动原生 App
- 插件市场

### 退出条件

- 用户可以长期使用而不依赖开发者手动维护。
- 数据可导出、可备份、可恢复。
- 核心 AI 链路有回归测试。
- UI 达到可对外演示水准。

---

## 技术优先级总表

| 优先级 | 方向 | 原因 |
|---|---|---|
| P0 | Memory understanding / ExtractedFact | 决定系统是否真的理解用户输入 |
| P0 | Retrieval eval harness | 没有评估就无法可靠改进 RAG |
| P0 | Temporal + structured query | 支撑消费、情绪、计划类问题 |
| P1 | Hybrid retrieval | 提升召回质量 |
| P1 | Agentic workflow tracing | 支撑复杂 Agent 调试 |
| P1 | Long-term summary | 建立长期记忆能力 |
| P2 | Insight Agents | 提升产品价值感 |
| P2 | Notification policy | 提升主动性但需克制 |
| P3 | Multi-Agent orchestration | 有基础评估和可观测后再做 |
| P3 | Productization hardening | 进入长期使用前必须完成 |

## 下一步建议

严格从 Phase 7 开始，不要跳到多 Agent。

下一轮最小切片：

1. 新增 `ExtractedFact` 模型和 repo。
2. 实现 expense / mood / plan / learning 四类抽取 schema。
3. 新增 memory 创建后的 fact extraction service。
4. Memory Detail 展示 extracted facts。
5. 准备 10 条 fact extraction smoke cases。

