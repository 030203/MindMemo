# MindMemo 全阶段开发计划

**日期**: 2026-06-25  
**总周期**: 12 周 (3 个月)  
**策略**: 渐进式重构，每个模块标注完整内部流程，测试点一一对应

---

## 产品定位（决定架构边界）

MindMemo 是「个人第二大脑」，目标人群**可能记录任何事情**（学习/工作/生活/情绪/灵感/健康/待办）。

**两条铁律（v1.2 新增，约束所有链路设计）：**

1. **记录与对话职责分离**：记录走**专门的记录窗口**（确定性 CRUD，用户显式输入），
   对话层（LLM）**只读**——基于用户已记录的内容做问答与分析，**不直接写库**。
   - LLM 自主 CRUD 作为**后续能力**，未来以 tool 形式接入，且必须走「解析草稿 → 用户确认 → 落库」，不允许黑盒静默写入。
2. **对话的核心是"问 TA 自己记的东西"**，不是通用百科问答。路由与测试都围绕「对个人记录的对话」设计。

## 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    SHARED MEMORY (横向共享层)                 │
│  Working | Episodic | Semantic | Goal | Procedural | Insights │
└─────────────────────────────────────────────────────────────┘
              ▲               ▲               ▲
              │  (对话层只读)   │               │
┌─────────────┴───────────────┴───────────────┴──────────────┐
│  USER ─┬─→ [记录窗口] ──→ MemoryService (确定性CRUD)         │
│        │                                                     │
│        └─→ [对话] → Router ─┬─ fast ──→ QA Agent (单轮,只读)  │
│                             │                                │
│                             └─ slow ──→ 二段决策(Planner评估) │
│                                  ├─ ReAct        (探索式多步) │
│                                  ├─ Plan→ReAct   (可预拆解)   │
│                                  └─ Multi-Agent  (并行/分角色)│
│                                         │                    │
│                                         ▼                    │
│                                  Tool Registry               │
│                            (纯Python实现，无LangChain)        │
│                                                              │
│  [异步] Insight Agent / Memory Manager                       │
└──────────────────────────────────────────────────────────────┘
```

### slow 三层分级（v1.3 更新）

slow 内部有三条执行路径，由 **SlowRouter（二级路由）** 分流，用一次轻量 LLM 调用判定任务结构：

| 路径 | 触发条件（任务结构） | 例子 |
|------|------|------|
| **ReAct** | 步骤数未知、探索式，默认路径 | "我上周记了啥跟算法有关的" |
| **Plan→ReAct** | 任务可预先拆解为固定步骤，防止乱逛 | "对比我记的两个健身方案" |
| **Multi-Agent** | 需并行扇出大量记录 或 多角色分工 | "生成我这个月的学习月报" |

落地顺序：**先建 SlowRouter + ReAct（slow 全走 ReAct）→ 看到乱逛/步数爆炸再实现 Plan → 重型报告再上 Multi-Agent**。痛点驱动，不预先猜。SlowRouter 接口从 Phase 3-A 就定好，后续只是往里填实现。

### 核心链路

| 链路 | 输入 | 经过 | 输出 | 同步? |
|------|------|------|------|--------|
| 记录 | 记录窗口显式输入 | MemoryService CRUD | 落库 | 同步(非LLM) |
| Fast QA | 对记录的简单问答/闲聊 | Router→QA Agent(只读)→1次LLM | 答案+来源 | 同步 |
| Slow ReAct | 对记录的探索式多步 | Router→Planner评估→ReAct多轮→工具(只读) | 答案+来源 | 同步 |
| Slow Plan | 可预拆解的多步任务 | + Planner 显式拆解 | 答案+来源 | 同步 |
| Slow Multi | 重型报告/并行分析 | + 多 Agent 协作 | 报告 | 同步 |
| Insight (异步A) | (后台) | 读Memory→分析 | 写Insights缓存 | 异步 |
| Memory Manager (异步B) | (后台) | 扫Memory | 去重/关联/衰减 | 异步 |

---

## Phase 进度总览

| Phase | 名称 | 状态 | 周期 |
|-------|------|------|------|
| 0 | 基础设施搭建 | ✅ 完成 | Week 1 |
| 1 | 分层记忆重构 | ✅ 完成 | Week 2-3 |
| 2 | 工具系统 + Fast 链路 | ✅ 完成 | Week 4-5 |
| 3 | Slow 链路 — SlowRouter + ReAct / Plan / Multi-Agent | ✅ 完成 | Week 6-8 |
| 4 | 异步链路 (Insight Agent + Memory Manager) | ✅ 完成 | Week 8-9 |
| 5 | 端到端集成 + 前端对接 | ⬜ 待开始 | Week 10-12 |

---

---

# Phase 0: 基础设施搭建 ✅

**目标**: 搭建纯 Python 的 Agent/Tool/Memory 骨架，充分注释，模块解耦，便于独立测试。

**完成日期**: 2026-06-24  
**测试**: 40 个用例通过  
**详细记录**: `docs/phase0_completion_summary.md`

### 产出

```
backend/app/
├── agent/
│   ├── __init__.py
│   └── base.py                 # ✅ BaseAgent + AgentContext
├── memory/
│   ├── __init__.py
│   ├── manager.py              # ✅ MemoryManager (门面模式)
│   └── layers/
│       ├── working.py          # ✅ WorkingMemory (纯内存, 对话历史+上下文变量)
│       ├── episodic.py         # ⏳ 骨架
│       ├── semantic.py         # ⏳ 骨架
│       ├── goal.py             # ⏳ 骨架
│       ├── procedural.py       # ⏳ 骨架
│       └── insight.py          # ⏳ 骨架
├── tools/
│   ├── base.py                 # ✅ BaseTool + ToolResult + ToolParameter
│   ├── registry.py             # ✅ ToolRegistry (单例, 线程安全)
│   ├── retrieval/              # ⏳ 空目录
│   ├── memory/                 # ⏳ 空目录
│   └── external/               # ⏳ 空目录
├── llm/
│   └── client.py               # ✅ LLMClient (OpenAI SDK封装)
└── orchestration/
    └── __init__.py             # ⏳ 仅文档字符串
```

### 核心模块设计 — BaseAgent

```
============================================================
BaseAgent 生命周期 (模板方法模式):
============================================================

[步骤1] 外部调 agent.run(db, user_id, input_data, session_id)
         ↓
[步骤2] 创建 AgentContext (user_id, session_id, start_time)
         ↓
[步骤3] _pre_execute(db, user_id, input_data, context)
         典型用途: 从 MemoryManager 加载上下文、参数验证
         ↓
[步骤4] execute(db, user_id, input_data, context)  ← 子类实现
         核心决策逻辑: 调LLM、调工具、拼结果
         ↓
[步骤5] _post_execute(db, user_id, result, context)
         典型用途: 写回 WorkingMemory、记录轨迹
         ↓
[步骤6] 返回 result + _context 元数据
```

### 核心模块设计 — BaseTool

```
============================================================
Tool 调用链路:
============================================================

[步骤1] Agent 决定调工具 → self._call_tool(tool_name, tool_input, context)
         ↓
[步骤2] 从 ToolRegistry 获取工具实例 → registry.get_tool(tool_name)
         ↓
[步骤3] 工具参数验证 → tool.validate_parameters(**tool_input)
         ↓
[步骤4] 执行 → tool.execute(**tool_input)  → 返回 ToolResult
         ↓
[步骤5] 记录到 AgentContext → context.add_action(tool_name, tool_input, result)
```

### 核心模块设计 — MemoryManager

```
============================================================
MemoryManager 门面模式:
============================================================

mm = MemoryManager(db, user_id)
  │
  ├─ mm.working          → WorkingMemory (纯内存, 对话历史)
  ├─ mm.episodic         → EpisodicMemory (调用 memory_repository)
  ├─ mm.semantic         → SemanticMemory (聚合标签/实体/画像)
  ├─ mm.goal             → GoalMemory (调用 goal_repository)
  ├─ mm.procedural       → ProceduralMemory (调用 todo/reminder repo)
  └─ mm.insights         → InsightCache (调用 insight_repository)

快速上下文:
  mm.get_context_for_router()   → 轻量: 最近3轮对话 + 活跃目标 + 待办
  mm.get_context_for_planner()  → 完整: router上下文 + 用户画像 + 近期洞察
  mm.snapshot()                 → 全量: 所有层摘要
```

### 核心模块设计 — LLMClient

```
============================================================
LLMClient 三个调用层级:
============================================================

[层级1] chat(messages, model, functions)
         完整 OpenAI API 调用，支持 Function Calling
         ↓ 返回: {"choices": [{...}], "usage": {...}}

[层级2] simple_chat(prompt, system_message, model)
         简化接口: 拼 messages → chat() → 取 choices[0].message.content
         ↓ 返回: str (纯文本)

[层级3] function_call(messages, functions, force_function)
         Function Calling 专用: chat(functions=...) → 解析 function_call
         ↓ 返回: (function_name, arguments) | (None, None)

[层级4] parse_json(prompt, schema)
         结构化输出: 严格提示词 + 提取 markdown JSON → json.loads()
         ↓ 返回: dict | None (解析失败)
```

---

# Phase 1: 分层记忆重构 ✅

**目标**: 将 5 层记忆骨架全部接真实 Repository，创建 goals/insights 新表。

**完成日期**: 2026-06-25  
**测试**: 79 passed / 8 skipped  
**详细记录**: `docs/phase1_completion_summary.md`

### 产出

**新表**: `goals` / `memory_goal_links` / `insights`  
**新 Repo**: `goal_repo.py` / `insight_repo.py`  
**补全**: Episodic/Semantic/Goal/Procedural/Insight 5 层实现  
**测试**: 47 个新增用例 (repo 26 + integration 21)

---

# Phase 2: 工具系统 + Fast 链路 ✅ 完成

**目标**: 实现 7 个具体工具 + Router + QA Agent + QAWorkflow，打通第一条可用链路

**依赖**: Phase 0+1 完成  
**预计周期**: Week 4-5 (2周)

---

## Phase 2-A: 检索工具 (tools/retrieval/)

### 任务 2.1: HybridSearchTool

**文件**: `backend/app/tools/retrieval/hybrid_search.py`  
**依赖**: MemoryManager

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  query: str          # 搜索查询
  top_k: int = 10     # 返回条数
  category: str = None # 可选类别过滤

[步骤2] 关键词提取
  从 query 中提取关键词 (简单分词/去停用词)
  例: "我上周学了什么Python库" → ["上周", "Python", "库"]

[步骤3] 双路检索
  [3.1] 关键词匹配 (EpisodicMemory)
    调用 mm.episodic.get_recent_memories()
    用 keywords + category 过滤，按 importance_score 排序

  [3.2] 语义匹配 (SemanticMemory)
    调用 mm.semantic.search(query)
    如果有 embedding_service，做向量相似度
    如果没有，fallback 到关键词匹配

[步骤4] 合并排序
  - 合并两路结果，按 relevance_score 降序
  - 去重: 同一 memory_id 只保留分数更高的
  - 截断 top_k

[步骤5] 返回 ToolResult
  ToolResult(
    success=True,
    data={
      "results": [{"memory_id", "title", "summary", "relevance", "source"}, ...],
      "total_matches": 25,
      "query": "我上周学了什么Python库"
    }
  )

============================================================
测试要点:
  1. 精确匹配: "Python" → 返回标题含 Python 的记忆
  2. 空结果: "火星基地" → 返回空列表, success=True
  3. 类别过滤: category="笔记" → 只返回笔记类型
  4. top_k 截断: top_k=3 → 最多返回 3 条
============================================================
```

### 任务 2.2: TimeResolverTool

**文件**: `backend/app/tools/retrieval/time_resolver.py`  
**依赖**: LLMClient (规则失败时兜底)

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  time_expression: str  # "上周", "本月", "最近3天"

[步骤2] 规则优先解析 (不调 LLM，速度快)
  规则表:
    "今天"     → 今天 00:00 ~ 23:59
    "昨天"     → 昨天 00:00 ~ 23:59
    "本周"     → 本周一 ~ 本周日
    "上周"     → 上周一 ~ 上周日
    "本月"     → 本月1日 ~ 本月最后一天
    "上个月"   → 上月1日 ~ 上月最后一天
    "最近N天"  → N天前 ~ 今天
    "最近N周"  → N*7天前 ~ 今天
    "最近N月"  → N*30天前 ~ 今天

[步骤3] 规则未命中 → LLM 兜底
  调 LLMClient.parse_json(
    prompt=time_expression,
    schema={
      "type": "object",
      "properties": {
        "start": {"type": "string", "description": "开始日期 ISO 8601"},
        "end": {"type": "string", "description": "结束日期 ISO 8601"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
      }
    }
  )

[步骤4] 返回 ToolResult
  ToolResult(
    success=True,
    data={
      "start": "2026-06-16T00:00:00+08:00",
      "end": "2026-06-22T23:59:59+08:00",
      "confidence": 0.95,
      "resolution_method": "rule" | "llm"
    }
  )

============================================================
测试要点:
  1. "今天" → 正确日期范围
  2. "上周" → 周一~周日
  3. "最近3天" → 3天前~今天
  4. "去年三月" → LLM兜底, confidence < 1.0
  5. "香蕉" → success=False, error="无法解析"
============================================================
```

### 任务 2.3: FactExtractorTool

**文件**: `backend/app/tools/retrieval/fact_extractor.py`  
**依赖**: LLMClient.parse_json

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  text: str              # 待提取的文本
  max_facts: int = 10    # 最多提取几条事实

[步骤2] 文本预处理
  - 截断过长文本 (max 4000 chars)
  - 分段: 按段落/句子切分

[步骤3] LLM 结构化提取
  调 LLMClient.parse_json(prompt=text, schema=FACT_SCHEMA)
  提取 (subject, predicate, object, confidence) 四元组

[步骤4] 去重 + 排序
  - 相同三元组只保留 confidence 最高的
  - 按 confidence 降序

[步骤5] 返回 ToolResult
  ToolResult(
    success=True,
    data={
      "facts": [
        {"subject": "用户", "predicate": "学习了", "object": "Python闭包", "confidence": 0.95},
      ],
      "total_extracted": 5,
      "source_text_length": 500
    }
  )

============================================================
测试要点:
  1. 简单句: "我昨天学了Python" → 1条事实
  2. 多事实: 一段话含3个知识点 → 3条事实
  3. 空文本: "" → 空列表, success=True
============================================================
```

---

## Phase 2-B: 记忆工具 (tools/memory/)

### 任务 2.4: RelationFinderTool

**文件**: `backend/app/tools/memory/relation_finder.py`  
**依赖**: MemoryManager (EpisodicMemory + SemanticMemory)

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  memory_id: UUID               # 源记忆ID
  max_relations: int = 10

[步骤2] 获取源记忆
  调用 mm.episodic.get_by_id(memory_id)
  提取 tags / keywords / entities / category / time_info

[步骤3] 多维相似度匹配 (规则引擎，不调 LLM)
  [3.1] 标签重叠: 共享 tags 越多 → 分数越高
  [3.2] 关键词重叠: Jaccard 相似度
  [3.3] 实体重叠: 共享 entities (人名/地名/技术名)
  [3.4] 时间接近: event_time 在 24h 内 → 加分
  [3.5] 同类别: 相同 category → 加分

[步骤4] 合并排序
  - 加权合并所有维度分数
  - 去重 (排除自身)
  - 按综合分数降序，取 top max_relations

[步骤5] 返回 ToolResult
  ToolResult(
    success=True,
    data={
      "source_memory_id": "uuid-xxx",
      "relations": [
        {"target_memory_id": "uuid-yyy", "score": 0.85,
         "overlap_fields": ["tags", "keywords"],
         "explanation": "共享 3 个标签: Python, 编程, 学习"}
      ]
    }
  )

============================================================
测试要点:
  1. 有关联: 两条都有 "Python" 标签 → 返回关系
  2. 无关联: 完全不相关的记忆 → 空列表
  3. 排除自身: 不会把自己列为关联
============================================================
```

### 任务 2.5: MemoryWriteTool

**文件**: `backend/app/tools/memory/memory_write.py`  
**依赖**: MemoryService + memory_repository

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  title: str           # 标题
  content: str         # 正文
  category: str = None # 类别
  tags: list[str] = [] # 标签
  source: str = "agent"

[步骤2] 内容清洗
  去HTML/去多余空格/截断过长内容

[步骤3] AI 增强
  如果 category 为空 → 调 LLM 自动分类
  如果 tags 为空 → 调 LLM 自动提取标签/关键词
  生成 content_summary (不超过 200 字)

[步骤4] 写入数据库
  调用 memory_repository.create()

[步骤5] 触发 ReviewQueue (低置信度保护)
  如果 AI 自动分类置信度 < 0.7:
    创建 ReviewQueue 条目: "请确认这条记忆的分类和标签"
  ↑ 关键安全措施: 防止 AI 乱分类污染记忆库

[步骤6] 写 Timeline
  创建 timeline_event: "创建了记忆: {title}"

[步骤7] 返回 ToolResult
  ToolResult(
    success=True,
    data={
      "memory_id": "uuid-xxx",
      "title": "Python闭包笔记",
      "category": "学习笔记",
      "tags": ["Python", "闭包", "编程"],
      "needs_review": False
    }
  )

============================================================
测试要点:
  1. 完整写入: title+content+category+tags → 成功入库
  2. 自动分类: category 为空 → AI 分类 → 入库
  3. ReviewQueue触发: 低置信度 → needs_review=True
  4. 空标题: title="" → success=False
  5. 超长内容: 3000字 → 自动截断 + 摘要
============================================================
```

---

## Phase 2-C: 外部工具 (tools/external/)

### 任务 2.6: WebSearchTool

**文件**: `backend/app/tools/external/web_search.py`  
**依赖**: Tavily API

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  query: str              # 搜索关键词
  max_results: int = 5

[步骤2] 调用搜索 API
  调用 Tavily API → 超时5s → 最多重试2次

[步骤3] 结果格式化
  每条结果: {title, url, snippet, published_date}

[步骤4] 返回 ToolResult
  ToolResult(
    success=True,
    data={
      "results": [{"title": "...", "url": "...", "snippet": "..."}],
      "query": "Python闭包",
      "total_results": 5
    }
  )

============================================================
测试要点:
  1. 正常搜索: "Python" → 返回结果列表
  2. API不可用 → success=False, 有错误信息, 不崩溃
============================================================
```

### 任务 2.7: WeatherTool

**文件**: `backend/app/tools/external/weather.py`  
**依赖**: OpenWeather API

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  city: str              # 城市名
  date: str = "today"    # today/tomorrow/ISO date

[步骤2] 日期解析
  如果 date 不是 ISO 格式 → 调用 TimeResolverTool 解析

[步骤3] 调用天气 API
  调用 OpenWeather API → 超时5s

[步骤4] 返回 ToolResult
  ToolResult(
    success=True,
    data={
      "city": "北京",
      "date": "2026-06-25",
      "temperature": {"min": 22, "max": 30},
      "condition": "晴",
      "humidity": 45,
      "suggestion": "适合户外活动"
    }
  )

============================================================
测试要点:
  1. 北京今天 → 返回天气数据
  2. API不可用 → success=False, 不崩溃
============================================================
```

---

## Phase 2-D: 编排层 — Fast 链路

### 任务 2.8: Router (意图路由)

**文件**: `backend/app/orchestration/router.py`  
**依赖**: LLMClient + MemoryManager

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收输入
  user_message: str + user_id: UUID

[步骤2] 加载 Router 上下文
  调用 MemoryManager.get_context_for_router() 获取:
    - recent_conversation: 最近 3 轮对话 (WorkingMemory)
    - active_goals: 用户当前活跃目标 (GoalMemory)
    - pending_todos: 待办事项 (ProceduralMemory)
  目的: 路由决策需要上下文
    例: 用户刚说"帮我分析学习记录"，下一句"那Python呢？"
    只看"那Python呢？"会误判为 simple → 必须结合上下文判定 slow

[步骤3] 构造路由 Prompt
  system_prompt = '''你是一个意图分类器。分析用户输入，判断问题复杂度。
  
  用户当前上下文:
  - 活跃目标: {active_goals}
  - 待办事项: {pending_todos}
  - 最近对话: {recent_conversation}
  
  分类规则:
  - "fast": 简单问答、单次查询、闲聊、单一操作
    例: "什么是闭包？"、"记一条笔记：明天开会"、"今天天气怎样"
    
  - "slow": 需要多步推理、跨时间分析、创建多个任务、调外部工具
    例: "分析我最近一周的学习情况并规划下周"、"帮我整理所有Python笔记"
  
  返回 JSON: {"complexity": "fast"|"slow", "reason": "", "suggested_tools": []}
  '''

[步骤4] 调 LLM 分类
  调用 LLMClient.parse_json(
    prompt=user_prompt, 
    system_message=system_prompt, 
    schema=ROUTER_SCHEMA
  )

[步骤5] 返回路由结果
  RouterResult(complexity="fast"|"slow", reason=str, suggested_tools=list[str])

[步骤6] 记录路由日志
  context.metadata["router_decision"] = router_result

============================================================
测试要点:
  1. "你好" → fast
  2. "帮我记个笔记" → fast  
  3. "分析最近一个月的学习记录并制定下周计划" → slow
  4. 连续上下文: 先问"最近学了什么"再问"那Django呢" → slow (上下文感知)
============================================================
```

### 任务 2.9: QA Agent (Fast 路径)

**文件**: `backend/app/agent/qa_agent.py`  
**依赖**: BaseAgent + ToolRegistry + MemoryManager

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收输入 (父类 BaseAgent.run() 调用)
  input_data = {
    "question": "用户问题原文",
    "router_result": {"complexity": "fast", "reason": "...", "suggested_tools": []}
  }

[步骤2] _pre_execute — 加载记忆上下文
  从 MemoryManager 加载:
    - working.get_recent_turns(n=5) → 最近 5 轮对话
    - episodic.get_recent_memories(days=7, limit=5) → 最近一周记忆
    - goal.get_active_goals(limit=5) → 活跃目标
  存储到 context.variables:
    context.variables["working_context"] = recent_turns
    context.variables["episodic_context"] = recent_memories
    context.variables["goal_context"] = active_goals

[步骤3] execute — 构造 Prompt + 调 LLM
  [3.1] 拼装 system prompt
    system_prompt = f'''你是 MindMemo，一个个人记忆助手。
    
    用户活跃目标: {active_goals}
    用户最近记忆: {recent_memories}
    对话历史: {conversation_history}
    
    回答规则:
    1. 基于用户记忆回答问题，优先引用记忆中的信息
    2. 如果问题与记忆无关，当做通用知识问答
    3. 回答简洁，不要编造记忆中没有的信息
    4. 如果用户说"记下来"、"帮我记"，请调用 memory_write 工具
    '''

  [3.2] 拼装 messages
    messages = [
      {"role": "system", "content": system_prompt},
      *conversation_history,       # 展开历史对话
      {"role": "user", "content": question}
    ]

  [3.3] 决策: 是否需要工具
    如果 suggested_tools 非空 或 检测到记忆操作意图:
      → LLMClient.chat(messages, functions=available_tool_schemas)
      → 如果 LLM 返回 function_call → _call_tool() 执行 → 追加结果 → 再调 LLM
      → 返回最终回答
    否则:
      → LLMClient.chat(messages) 直接生成回答

  [3.4] 返回结果
    return {
      "status": "success",
      "data": {
        "answer": "LLM 的回答文本",
        "sources": [{"memory_id": "xxx", "title": "Python笔记", "relevance": 0.9}],
        "tool_calls_made": [{"tool": "memory_write", "result": "success"}]
      }
    }

[步骤4] _post_execute — 写回记忆
  [4.1] 更新 WorkingMemory
    mm.working.add_turn("user", question)
    mm.working.add_turn("assistant", answer)

  [4.2] 记录到 EpisodicMemory (如果问题有实质内容)
    判断标准: 涉及用户数据、有信息量 → 写入 memory_items
    闲聊如"你好"、"谢谢" → 不写入

  [4.3] 记录 QA 日志 (用于统计)

============================================================
测试要点:
  1. 简单知识问答: "什么是闭包？" → 直接 LLM 回答
  2. 记忆查询: "我昨天学了什么？" → 检索 episodic → 引用来源
  3. 带工具调用: "帮我记个笔记：明天下午3点开会" → 调 MemoryWriteTool
  4. 对话连续性: 连续问3个问题，WorkingMemory 正确传递上下文
============================================================
```

### 任务 2.10: QAWorkflow (编排)

**文件**: `backend/app/orchestration/qa_workflow.py`  
**依赖**: Router + QA Agent

```
============================================================
内部处理流程 (核心编排):
============================================================

[步骤1] 入口: handle_question(db, user_id, question)
  API 层调用的唯一入口

[步骤2] 初始化 MemoryManager
  mm = MemoryManager(db, user_id)

[步骤3] 初始化 Router + QA Agent
  router = Router(llm_client=LLMClient())
  agent = QAAgent(name="qa_agent", memory_manager=mm, tool_registry=registry)

[步骤4] 路由决策
  # === 意图分析 ===
  router_result = await router.route(message=question, memory_manager=mm, ...)
  # → {"complexity": "fast"|"slow", "reason": "...", "suggested_tools": [...]}

[步骤5] 分支执行
  if router_result.complexity == "fast":
    # === Fast: QA Agent 直接回答 ===
    result = await agent.run(
      db=db, user_id=user_id,
      input_data={"question": question, "router_result": router_result}
    )

  elif router_result.complexity == "slow":
    # === Slow: 暂时降级为 QA Agent (Phase 3 实现后接入 Planner+ReAct) ===
    result = await agent.run(
      db=db, user_id=user_id,
      input_data={"question": question, "router_result": router_result}
    )

[步骤6] 写回 WorkingMemory
  mm.working.add_turn("user", question)
  mm.working.add_turn("assistant", result["data"]["answer"])

[步骤7] 返回给 API 层
  return result
  # {"status": "success", "data": {"answer": "...", "sources": [...]}}

============================================================
测试要点 (集成测试):
  1. "你好" → router=fast → QA Agent → 返回回答
  2. Slow 降级: 复杂问题 → 目前降级为 QA Agent → 正常返回
  3. 记忆留存: 问完后再问"刚才问了什么" → WorkingMemory 有记录
  4. 错误处理: LLM 挂了 → 返回友好错误, 不 500
============================================================
```

### 任务 2.11: 接入 API 端点

**文件**: `backend/app/api/v1/qa.py` (改造)  
**依赖**: QAWorkflow

```
============================================================
改造内容:
============================================================

[改造前]
  POST /qa/ask → qa_service.answer_question()
    → llm_answer_service.chat(question)   # 无记忆上下文, 无路由

[改造后]
  POST /qa/ask → qa_service.answer_question()
    → qa_workflow.handle_question(db, user_id, question)
      → Router → QA Agent (带记忆上下文) → LLM
      
新特性:
  - 回答基于用户记忆上下文
  - 回答带来源引用 (sources)
  - 自动记录对话历史到 WorkingMemory

保留兼容:
  - Schema 不变 (SimpleQARequest / SimpleQAResponse)
  - LLM 不可用时返回友好错误消息
============================================================
```

---

## Phase 2 验收标准

```python
# 工具系统
registry = ToolRegistry()
registry.register(HybridSearchTool)
registry.register(TimeResolverTool)
registry.register(FactExtractorTool)
registry.register(RelationFinderTool)
registry.register(MemoryWriteTool)
registry.register(WebSearchTool)
registry.register(WeatherTool)
assert len(registry.list_tool_schemas()) == 7

# Fast 链路端到端
# POST /qa/ask  {"question": "什么是闭包？"}
# → {"code": 0, "data": {"answer": "闭包是...", "sources": [...]}}
```

### Phase 2 执行记录

| # | 任务 | 日期 | 状态 | 测试结果 |
|---|------|------|------|---------|
| 2.1 | HybridSearch | 2026-06-26 | ✅ | 13 用例通过 |
| 2.2 | TimeResolver | 2026-06-26 | ✅ | 16 用例通过 |
| 2.3 | FactExtractor | 2026-06-26 | ✅ | 10 用例通过 |
| 2.4 | RelationFinder | 2026-06-26 | ✅ | 11 用例通过 |
| 2.5 | MemoryWrite | 2026-06-26 | ✅ | 13 用例通过 |
| 2.6 | WebSearch | 2026-06-26 | ✅ | 6 用例通过 (含 Weather 共 12) |
| 2.7 | Weather | 2026-06-26 | ✅ | 6 用例通过 |
| 2.8 | Router | 2026-06-26 | ✅ | 13 用例通过 (规则 7 + LLM 5 + helper 1) |
| 2.9 | QA Agent | 2026-06-26 | ✅ | 8 用例通过 |
| 2.10 | QAWorkflow | 2026-06-26 | ✅ | 5 用例通过 |
| 2.11 | API接入 | 2026-06-26 | ✅ | qa_service → qa_workflow，真实 DeepSeek E2E 通过 |

**Phase 2 合计**: 全量回归 188 passed。Fast 链路 (Router → QA Agent → QAWorkflow → /ask API) 真实 DeepSeek 端到端验证通过。
**注**: slow 链路当前由 QA Agent 兜底，Planner + ReAct 在 Phase 3 接入。

---

---

# Phase 3: Slow 链路 — SlowRouter + ReAct / Plan / Multi-Agent ⬜

**目标**: 实现 slow 路径完整闭环。slow 内部有三条执行路径，由 SlowRouter 二级路由分流。

**依赖**: Phase 2 完成 (7个工具 + ToolRegistry + Router fast/slow 二分类可用)
**预计周期**: Week 6-8 (分三个子阶段，痛点驱动)

---

## slow 内部架构

```
slow → SlowRouter（二级路由，LLM 判定）
           │
           ├─ react        → ReAct Agent     （默认，探索式单/多轮）
           ├─ plan         → Planner + ReAct  （可预拆解的固定步骤任务）
           └─ multi_agent  → Multi-Agent Coordinator（并行扇出/多角色分工）
```

**判定维度**（SlowRouter）：

| 路径 | 触发条件（任务结构） | 例子 |
|------|------|------|
| **react** | 探索式，步骤数未知，默认 | "我昨天记了啥"、"帮我找找和Python相关的笔记" |
| **plan** | 任务可预先拆解为固定步骤，需防止乱逛 | "对比我记的两个健身方案"、"制定下周计划" |
| **multi_agent** | 需并行扇出大量记录 或 多角色分工 | "生成我这个月的学习月报" |

**SlowRouter 用轻量 LLM 调用**（不用纯规则），原因：任务结构比意图更难规则化；失败降级到 react（默认值无损失）。

---

## Phase 3-A: SlowRouter + ReAct Agent（先做，slow 默认路径）

### 任务 3.1: SlowRouter（二级路由）

**文件**: `backend/app/orchestration/slow_router.py`
**依赖**: LLMClient

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收输入
  user_message: str      # 原始用户问题
  memory_context: dict   # 来自 MemoryManager 的轻量上下文（最近对话+目标）

[步骤2] LLM 轻量判定
  用一次 parse_json 判定任务结构：
    - react:       步骤数未知，探索式，每步单工具推进
    - plan:        任务可预先列出固定步骤（3-7步），执行顺序固定
    - multi_agent: 需并行处理大量记录 OR 需要多个独立 Agent 分角色协作

[步骤3] 失败降级
  LLM 不可用 / 解析失败 → 默认 react（安全兜底）

[步骤4] 返回 SlowRouterResult
  path: "react" | "plan" | "multi_agent"
  reason: str
  decided_by: "llm" | "fallback"

============================================================
测试要点:
  1. "我昨天记了啥" → react（单轮检索）
  2. "帮我找所有Python相关笔记" → react（探索式多轮）
  3. "对比我记的两个健身方案" → plan（固定步骤：取A→取B→比较）
  4. "制定我下个月的学习计划" → plan
  5. "生成我这个月的学习月报" → multi_agent（大量记录并行）
  6. LLM不可用 → react（fallback）
============================================================
```

---

### 任务 3.2: ReAct Agent（探索式多轮推理）

**文件**: `backend/app/agent/react_agent.py`
**依赖**: BaseAgent + ToolRegistry + LLMClient

```
============================================================
ReAct Agent 是什么:
  slow 路径的默认执行引擎，无需预先规划，动态决策每一步。
  按 Thought → Action → Observation 循环，直到能给出完整回答。

ReAct 循环示意（"我上周记了哪些Python相关的内容"）:

  Round 1:
    Thought: 需要检索用户上周的笔记，关键词 Python
    Action: hybrid_search(query="Python", time_range="7d")
    Observation: 找到 8 条记录，主要是闭包/装饰器/异步

  Round 2:
    Thought: 已有足够数据，可以整理回答
    → 无需再调工具，直接生成
    最终回答: "你上周记了以下Python内容：..."

============================================================
内部处理流程:
============================================================

[步骤1] 接收输入
  input_data = {
    "question": "用户问题",
    "slow_router_result": {"path": "react", ...}
  }

[步骤2] _pre_execute — 加载记忆上下文
  调用 MemoryManager 加载：
    - working.get_recent_turns(n=5)
    - episodic.get_recent_memories(days=7, limit=10)
    - goal.get_active_goals()

[步骤3] execute — ReAct 主循环

  MAX_ROUNDS = 10  # 安全上限，防止死循环
  messages = [system_prompt, {"role": "user", "content": question}]
  
  for round_num in range(MAX_ROUNDS):
  
    [3.1] Thought 阶段
      调 LLMClient.chat(messages, functions=all_tool_schemas)
      LLM 返回 function_call 或纯文本

    [3.2] Action 阶段（LLM 决定调工具时）
      tool_result = await self._call_tool(name, args, context)
      记录 context.add_action(name, args, tool_result)

    [3.3] Observation 阶段
      将 tool_result 追加到 messages
      messages.append({"role": "tool", "content": tool_result})

    [3.4] 终止判断
      LLM 没有调工具（直接生成回答）→ break
      或 MAX_ROUNDS 触发 → break（返回 partial）

  [3.5] 生成最终回答
    最后一轮 LLM 输出即为回答

[步骤4] _post_execute — 写回 WorkingMemory
  mm.working.add_turn("user", question)
  mm.working.add_turn("assistant", answer)

[步骤5] 返回结果
  {
    "status": "success",
    "data": {
      "answer": "最终回答",
      "sources": [{"memory_id", "title", "relevance"}],
      "tool_calls_made": N,
      "rounds": round_num
    }
  }

============================================================
测试要点:
  1. 简单查询（1轮）: "我记过妈妈生日吗" → search 1次 → 回答
  2. 多轮探索: "帮我找所有Python笔记" → 2-3轮 → 汇总回答
  3. MAX_ROUNDS 保护: mock 工具永远返回"继续" → 10轮后返回 partial
  4. 无记录: 搜索无结果 → 诚实回答"未找到"，不编造
  5. 来源引用: 回答中 sources 包含实际用到的 memory_id
============================================================
```

---

### 任务 3.3: QAWorkflow 接入 SlowRouter + ReAct

**文件**: `backend/app/orchestration/qa_workflow.py`（改造）

```
============================================================
改造内容：替换 slow 路径降级逻辑
============================================================

[改造前 Phase 2]:
  elif router_result.complexity == "slow":
    result = await qa_agent.run(...)   # 降级为 QA Agent

[改造后 Phase 3-A]:
  elif router_result.complexity == "slow":
    # === 二级路由 ===
    slow_router = SlowRouter(llm_client=LLMClient())
    slow_result = await slow_router.route(
      user_message=question,
      memory_context=mm.get_context_for_router()
    )

    if slow_result.path == "react":
      react_agent = ReActAgent(memory_manager=mm, tool_registry=registry)
      result = await react_agent.run(db, user_id, {"question": question, ...})

    elif slow_result.path == "plan":
      # Phase 3-B 实现，当前降级为 react
      result = await react_agent.run(...)

    elif slow_result.path == "multi_agent":
      # Phase 3-C 实现，当前降级为 react
      result = await react_agent.run(...)
============================================================
```

---

## Phase 3-B: Planner（Plan 路径，看到 ReAct 乱逛再加）

### 任务 3.4: Planner（任务规划器）

**文件**: `backend/app/orchestration/planner.py`
**触发时机**: SlowRouter 判定 path=plan 时调用

```
============================================================
Planner 是什么:
  把可预拆解的任务拆成固定步骤序列，以"建议步骤"形式注入给 ReAct，
  防止 ReAct 在结构化任务中乱逛（搜错方向、重复搜索）。

  例: "对比我记的两个健身方案"
  → [
      {step: 1, description: "检索健身方案A相关记录", tool_name: "hybrid_search", hint: "query=健身方案A"},
      {step: 2, description: "检索健身方案B相关记录", tool_name: "hybrid_search", hint: "query=健身方案B"},
      {step: 3, description: "对比两个方案，生成对比结论", tool_name: null, hint: "综合step1和step2的结果"},
    ]

  Plan 的约束方式（宽松模式）:
    不新建 PlanExecutor，不强制 ReAct 按步走。
    把步骤列表注入 ReActAgent 的 system_prompt 作为「建议执行顺序」，
    ReAct 仍然自由决策，但 LLM 看到明确指引后通常会按序执行。
    这样降级成本最低——plan 生成失败时直接走自由 ReAct。

============================================================
数据结构:
============================================================

PlanStep:
  step: int          # 步骤序号 (1-based)
  description: str   # 这步要做什么（自然语言）
  tool_name: str | None  # 用哪个工具；null = 纯 LLM 推理
  hint: str          # 参数提示，如 "query=健身方案A"

Plan:
  steps: list[PlanStep]
  task_description: str  # 整体任务描述（供 ReAct system prompt 使用）
  estimated_rounds: int  # 预估轮数

============================================================
Plan JSON Schema（LLM 返回格式）:
============================================================

{
  "type": "object",
  "properties": {
    "steps": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "step": {"type": "integer"},
          "description": {"type": "string"},
          "tool_name": {"type": "string", "nullable": true},
          "hint": {"type": "string"}
        },
        "required": ["step", "description"]
      }
    },
    "task_description": {"type": "string"},
    "estimated_rounds": {"type": "integer"}
  },
  "required": ["steps", "task_description"]
}

============================================================
Planner Prompt 模板:
============================================================

你是一个任务规划器，负责把用户的结构化需求拆解为可执行步骤序列。

可用工具（按需选择）：
{tool_list}
  - hybrid_search: 搜索用户记忆，输入关键词
  - fact_extractor: 从文本中提取结构化事实
  - time_resolver: 解析时间表达式
  - relation_finder: 查找记忆之间的关联
  - web_search: 搜索网络
  - weather: 查询天气

拆解规则：
1. 每步只做一件事
2. 需要工具的步骤指定 tool_name，纯推理/生成步骤 tool_name 为 null
3. 步骤数控制在 2~5 步，不要过度拆解
4. hint 说明关键参数（如 query 关键词），不要太具体（参数由 LLM 在执行时决定）
5. 如果任务不需要拆解（单步即可完成），返回1步计划

用户问题：{user_message}

============================================================
内部处理流程:
============================================================

[步骤1] 接收输入
  user_message: str
  tool_registry: ToolRegistry  # 获取可用工具列表

[步骤2] LLM 拆解
  调 parse_json(prompt=PLANNER_PROMPT, schema=PLAN_SCHEMA)

[步骤3] 验证
  - steps 非空，长度 2~5
  - 有 tool_name 的步骤，工具必须在 ToolRegistry 中存在
  - 验证失败 → 返回 None（调用方降级到自由 ReAct）

[步骤4] 返回 Plan（或 None）

[Plan 注入 ReAct]
  QAWorkflow 在调用 ReActAgent 前，把 plan 作为 input_data["plan"] 传入。
  ReActAgent 发现 input_data 有 plan 时，把步骤格式化成:
    「建议执行步骤:
     1. [描述] → 工具: hybrid_search (提示: query=健身方案A)
     2. [描述] → 工具: hybrid_search (提示: query=健身方案B)
     3. [描述] → 纯LLM推理」
  附加在 system_prompt 末尾。

============================================================
测试要点:
  1. "对比两个方案" → 生成3步计划（取A/取B/对比）
  2. "制定下周计划" → 生成3-4步计划
  3. 工具名不存在 → 验证失败返回 None，调用方降级 react
  4. LLM不可用 → 返回 None，降级 react
  5. plan 注入后 ReAct system_prompt 包含"建议执行步骤"字样
============================================================
```

---

## Phase 3-C: Multi-Agent Coordinator（重型任务，按需）

### 任务 3.5: Multi-Agent Coordinator + CreateSubAgentTool

**文件**:
- `backend/app/orchestration/multi_agent_coordinator.py`
- `backend/app/tools/agent/create_sub_agent.py`  ← 新工具

**触发时机**: SlowRouter 判定 path=multi_agent 时调用（月报/年报等重型任务）

```
============================================================
核心设计原则（v2，基于用户建议）:
============================================================

「创建子 Agent」是一个 Tool，而不是硬编码的分解逻辑。

  好处:
  1. Coordinator 本身是 ReActAgent，通过工具调用决策"何时/如何创建子 Agent"
  2. 子 Agent 的工具权限在 CreateSubAgentTool 的参数里声明，LLM 自己决定给多少
  3. 权限管理内嵌进工具调用层，不需要额外权限系统
  4. 深度硬约束：子 Agent 的工具集中绝不包含 create_sub_agent，防止无限嵌套

  例: "生成我这个月的学习月报"
  Coordinator ReAct 循环:
    Round1: Thought: 需要分析学习记录
            Action: create_sub_agent(
              question="分析这个月学习类笔记的主题和频率",
              allowed_tools=["hybrid_search", "time_resolver"],
              task_id="t1"
            )
            Observation: {"status": "created", "task_id": "t1"}

    Round2: Action: create_sub_agent(
              question="提取这个月学习的关键收获",
              allowed_tools=["hybrid_search", "fact_extractor"],
              task_id="t2"
            )
            Observation: {"status": "created", "task_id": "t2"}

    Round3: Action: collect_results(task_ids=["t1", "t2"])
            等待所有子 Agent 完成，收集结果
            Observation: {"t1": {answer, sources}, "t2": {answer, sources}}

    Round4: Thought: 数据够了，生成月报
            (纯LLM推理) → 生成最终月报

============================================================
工具权限分层:
============================================================

权限层级:
  ┌─ 顶层 (Top-level ReAct)
  │     可用工具: 全部6个 + create_sub_agent + collect_results
  │
  ├─ Coordinator (Multi-Agent 入口)
  │     可用工具: create_sub_agent + collect_results + 只读工具(hybrid_search等)
  │     注: Coordinator 本身也可以调工具（用于了解任务背景）
  │
  └─ SubAgent (深度1，不可再嵌套)
        可用工具: 由 Coordinator 在 create_sub_agent 调用时指定
        硬约束: 永远不包含 create_sub_agent（代码层强制过滤）
        上限: MAX_ROUNDS=5（比顶层 ReAct 的10轮更保守）

工具预设（Coordinator 可直接用名字引用）:
  "retrieval":  ["hybrid_search", "time_resolver"]
  "analysis":   ["fact_extractor", "relation_finder"]
  "external":   ["web_search", "weather"]
  "full_read":  ["hybrid_search", "time_resolver", "fact_extractor", "relation_finder"]

  实际传参时 Coordinator 可自由组合，预设只是提示词里的参考。

============================================================
CreateSubAgentTool 设计:
============================================================

文件: backend/app/tools/agent/create_sub_agent.py

name: "create_sub_agent"
description: "创建一个子 Agent 来处理特定子任务。子 Agent 有独立的工具权限。"

参数:
  task_id: str (required)       # 任务唯一标识，用于后续 collect_results 引用
  question: str (required)      # 子 Agent 的执行目标（自然语言）
  context: str (optional)       # 任务背景信息，帮助子 Agent 理解父任务
  allowed_tools: list[str] (required)  # 子 Agent 可用的工具名列表
                                        # create_sub_agent 会被自动过滤掉

execute(**kwargs) 流程:
  1. 校验 task_id、question 非空
  2. 过滤 allowed_tools：移除 "create_sub_agent"、"collect_results"
     （硬约束，代码层保证，不依赖 LLM 自觉）
  3. 检查当前已创建的子 Agent 数 ≤ 3（通过 kwargs["mailbox"].count() 判断）
     超过上限 → 返回 ToolResult(success=False, error="已达子 Agent 上限(3个)")
  4. 构建受限 ToolRegistry（只包含 allowed_tools 里的工具）
  5. 把 task Message 写入 mailbox（sub_agent_{task_id} 的 inbox）
  6. 返回 ToolResult(success=True, data={"task_id": task_id, "status": "created"})

  注: 子 Agent 的实际执行是异步的，create_sub_agent 只是创建任务并写信箱。
  Coordinator 后续调用 collect_results 等待并收集结果。

CollectResultsTool 设计:
  name: "collect_results"
  description: "等待指定子任务完成并收集结果（会阻塞直到全部完成或超时）"
  参数:
    task_ids: list[str] (required)  # 要收集的 task_id 列表
    timeout_seconds: int = 30       # 每个子 Agent 超时时间
  execute: asyncio.gather 等待所有子 Agent，超时则标记 failed，不抛出

============================================================
信箱（Mailbox）设计:
============================================================

Mailbox 是进程内共享对象，本轮对话生命周期内有效（不持久化）：

class Mailbox:
  slots: dict[str, MailboxSlot]     # agent_id → {inbox, outbox, registry}

  def create_slot(agent_id, tool_registry) → MailboxSlot
  def send(from_agent, to_agent, message: Message)
  def read_inbox(agent_id) → list[Message]
  def count_sub_agents() → int

Message 结构:
  msg_id: str           # UUID
  from_agent: str
  to_agent: str
  type: "task" | "result"
  task_id: str
  content: dict
    # type=task 时: {question, context, allowed_tools}
    # type=result 时: {answer, sources, status, error?}

============================================================
内部处理流程（Coordinator 是 ReActAgent）:
============================================================

[步骤1] QAWorkflow 构建 Coordinator
  在全局 ToolRegistry 基础上，额外注入:
    - CreateSubAgentTool(mailbox=mailbox)   ← 带信箱引用
    - CollectResultsTool(mailbox=mailbox)   ← 带信箱引用
  构建 Coordinator = ReActAgent(coordinator_registry, mailbox=mailbox)

[步骤2] Coordinator ReAct 循环（工具包含 create_sub_agent）
  Coordinator 自主决定：
    - 任务需要几个维度（创建几次 create_sub_agent）
    - 每个子 Agent 给什么工具（allowed_tools 参数）
    - 何时调 collect_results 收集结果

[步骤3] 子 Agent 并行执行
  每次 create_sub_agent 被调用时，把 Task 放入信箱
  collect_results 被调用时，触发 asyncio.gather 等待所有已创建的子 Agent
  子 Agent 从信箱认领任务，运行独立 ReAct 循环（MAX_ROUNDS=5）
  子 Agent 结果写回 coordinator 的 inbox

[步骤4] 汇总
  Coordinator 拿到 collect_results 的结果后，再做一轮纯 LLM 推理生成最终答案

============================================================
容错设计:
============================================================

  - 子 Agent 超时（>30s）→ status=failed，collect_results 返回 failed 占位
  - 子 Agent 工具全失败 → 返回"未找到相关记录"
  - 超出上限（create_sub_agent 第4次被调用）→ 返回 error，Coordinator 改变策略
  - 所有子 Agent failed → Coordinator 退化为单轮 LLM 直接回答（不返回错误给用户）
  - n=1 时（Coordinator 只创建了1个子 Agent）→ 效果等价于 ReAct，正常运行

============================================================
权限管理总结:
============================================================

  谁决定权限？  → Coordinator 的 LLM 在调用 create_sub_agent 时通过参数决定
  谁强制执行？  → CreateSubAgentTool.execute() 代码层过滤（不信任 LLM）
  不可绕过的约束（硬编码）:
    1. 子 Agent 工具集不含 create_sub_agent / collect_results（代码强制过滤）
    2. 子 Agent 数量 ≤ 3（Mailbox.count_sub_agents() 判断，超出直接报错）
    3. 子 Agent MAX_ROUNDS = 5（比 Coordinator 的10轮保守，控制成本）

============================================================
与3-B Planner的区别:
============================================================

  Planner: 同一条推理链，顺序拆步，防止 ReAct 乱逛（串行，步骤有依赖）
  Multi-Agent: 多条独立推理链，并行扇出（并行，维度独立，数据量大）

  判断标准:
    "对比两个方案"      → Plan（步骤1结果是步骤2的输入，串行）
    "生成月报/年报"     → Multi-Agent（各维度独立，可并行）

============================================================
测试要点:
  1. create_sub_agent 工具存在于 Coordinator registry 但不在 SubAgent registry
  2. create_sub_agent 调用4次 → 第4次返回 success=False（上限保护）
  3. allowed_tools 中含 create_sub_agent → 被自动过滤掉，子 Agent 没有该工具
  4. 月报流程: create×2 → collect → 纯LLM回答 → status=success
  5. 1个子 Agent timeout → collect_results 正常返回（含该 Agent 的 failed 占位）
  6. 所有失败 → Coordinator 最终仍给出回答，不崩溃
  7. Mailbox 消息路由: task 到对应 sub_agent inbox，result 回 coordinator inbox
============================================================
```

---

## Phase 3 验收标准

```python
# Phase 3-A 验收
# POST /qa/ask {"question": "我上周记了哪些Python相关的内容"}
# → Router: slow
# → SlowRouter: react
# → ReAct: 1-3 轮 Thought-Action-Observation
# → 回答带来源引用 sources

assert result["data"]["tool_calls_made"] >= 1
assert len(result["data"]["sources"]) > 0

# Phase 3-B 验收
# POST /qa/ask {"question": "对比我记的两个健身方案"}
# → SlowRouter: plan
# → Planner: 生成3步计划
# → ReAct: 按步执行

# Phase 3-C 验收
# POST /qa/ask {"question": "生成我这个月的学习月报"}
# → SlowRouter: multi_agent
# → Coordinator: 3个并行Agent + Summarizer
# → 返回结构化月报
```

### Phase 3 执行记录

| # | 任务 | 日期 | 状态 | 测试结果 |
|---|------|------|------|---------|
| 3.1 | SlowRouter | 2026-06-29 | ✅ | 13 用例通过 |
| 3.2 | ReAct Agent | 2026-06-29 | ✅ | 12 用例通过 |
| 3.3 | QAWorkflow 改造(3-A) | 2026-06-29 | ✅ | 9 用例通过，全量回归 231 passed |
| 3A-S | bootstrap 工具注入 + API async 化 | 2026-06-29 | ✅ | import 验证通过，6 个工具已注册 |
| 3.4 | Planner (3-B) | 2026-06-29 | ✅ | Plan schema + planner.py + QAWorkflow plan 分支 + ReAct plan 注入，全量 231 passed |
| 3.5 | Multi-Agent Coordinator (3-C) | 2026-06-29 | ✅ | Mailbox + CreateSubAgentTool + CollectResultsTool + coordinator 接线，全量 231 passed |

**Phase 3 合计**: 231 passed, 0 failed。SlowRouter + ReActAgent + Planner + Multi-Agent Coordinator 全部完成。
slow 路径已完整接入：fast → QAAgent；slow → SlowRouter → ReAct/Plan/Multi-Agent。

---

---

# Phase 4: 异步链路 ⬜

**目标**: 实现 Insight Agent (后台分析) + Memory Manager 异步维护

**依赖**: Phase 3 完成 (能调工具即可，异步链路不依赖 ReAct)  
**预计周期**: Week 8-9 (2周)

---

### 任务 4.1: Insight Agent (后台分析)

**文件**: `backend/app/agent/insight_agent.py`  
**触发**: 用户批量导入笔记后 / 定时任务 / 写入达到阈值

```
============================================================
Insight Agent 是什么:
  读取用户的记忆，分析出模式/趋势/洞察，写入 Insights 缓存

  例: 用户添加了 15 条笔记 → 异步触发
    → 分析: "最近 70% 内容关于机器学习，集中在晚上 9-11 点"
    → 写入 insights 表 (insight_type="pattern")

  下次用户问"我最近在忙啥？"
    → Fast 路径直接读 mm.insights.get_recent(days=7)
    → 秒回，不需要现场分析 15 条笔记

============================================================
内部处理流程:
============================================================

[步骤1] 触发条件 (择一)
  - 定时: 每天凌晨 2:00
  - 事件: 用户新增 > 10 条记忆
  - 手动: API 触发 /insights/generate

[步骤2] 读取源数据
  从 MemoryManager 加载:
    - episodic.get_recent_memories(days=7) → 最近一周记忆
    - episodic.get_summary(days=30) → 月度统计
    - procedural.get_pending_todos() → 待办统计
    - goal.get_active_goals() → 活跃目标进度

[步骤3] 多维度分析
  [3.1] 主题聚类
    用 tags/keywords 做词频统计 → 找出高频主题
    例: {"机器学习": 12, "Python": 8, "SQL": 3}

  [3.2] 时间模式
    按小时/星期统计活跃时段
    例: 最活跃: 21:00-23:00, 最不活跃: 周末

  [3.3] 目标进度
    检查 GoalMemory 中各目标的完成率
    例: "三个月掌握后端" 进度 60%

  [3.4] 习惯识别
    连续 N 天做同一类事 → 标记为习惯

[步骤4] LLM 生成自然语言洞察
  将步骤3的结构化数据给 LLM 生成自然语言描述:
    "你本周学习主要集中在机器学习领域(占70%)，"
    "学习时段集中在晚上9-11点，"
    "距离'掌握后端开发'目标还有40%进度，建议加速。"
    
  confidence_score = 基于数据量的置信度

[步骤5] 写入 Insights 缓存
  调用 insight_repository.create(
    user_id=user_id,
    insight_type="pattern"|"report"|"learning"|"project",
    title="本周学习分析",
    content=llm_generated_text,
    data=structured_data,  # 原始结构化数据 (供后续查询)
    confidence_score=0.85,
    expires_at=None  # 自然过期 (7天后)
  )

[步骤6] 返回 (如果手动触发)
  return {"status": "success", "data": {"insight_id": "xxx", "content": "..."}}

============================================================
测试要点:
  1. 有数据触发: 记忆>10条 → 生成洞察 → insights 表有记录
  2. 无数据: 记忆0条 → 不生成, 不崩溃
  3. 多类型: pattern / report / learning 类型都能生成
  4. 过期清理: 7天后旧 insights 标记过期
============================================================
```

### 任务 4.2: Memory Manager 异步维护

**文件**: `backend/app/memory/maintenance.py`  
**触发**: 定时任务 / 写入达到阈值

```
============================================================
Memory Manager 异步维护是什么:
  后台定期打扫记忆库，保证质量:

  职责1: 去重
    → 发现标题/内容高度相似的记忆 → 合并或标记
    例: "学了Docker" 记了3遍 → 合并为1条, 保留最早时间戳

  职责2: 关联
    → 发现应该关联但还没建 relation 的记忆
    例: "Docker笔记" 和 "K8s笔记" → 建立 memory_relation

  职责3: 衰减
    → 长期未被访问的记忆 → 降低 importance_score
    例: 半年没碰的"考四级"目标 → weight=0.1

============================================================
内部处理流程:
============================================================

[步骤1] 触发条件
  - 定时: 每天凌晨 3:00
  - 阈值: 新增记忆 > 50 条

[步骤2] 去重检查
  扫描最近 30 天的记忆:
    对每对记忆计算相似度 (标题 Jaccard + 内容余弦):
      相似度 > 0.85 → 标记为疑似重复
      创建 ReviewQueue 条目: "这两条记忆看起来是重复的，要合并吗？"
  ↑ 不自动合并，交给 ReviewQueue 让用户确认

[步骤3] 关联发现
  调用 RelationFinderTool 对最近记忆做批量关联:
    - 为每条新记忆查找相关记忆 (top 3)
    - 如果相似度 > 阈值 → 创建 memory_relation 记录

[步骤4] 权重衰减
  扫描所有记忆:
    last_accessed_at > 90天 → importance_score *= 0.5
    last_accessed_at > 180天 → importance_score *= 0.3
  扫描所有目标:
    status="paused" 且 paused > 60天 → 标记为可能废弃

[步骤5] 清理过期 Insights
  调用 insight_repository.delete_expired()

[步骤6] 返回维护报告
  MaintenanceReport(
    duplicates_found=3,
    new_relations=12,
    decayed_memories=5,
    expired_insights=2
  )

============================================================
测试要点:
  1. 重复检测: 插入2条相似记忆 → 触发去重 → ReviewQueue 增加
  2. 关联: 2条相关记忆 → 自动建立 relation
  3. 衰减: 模拟 last_accessed 半年 → importance_score 降低
  4. 空库: 无记忆 → 维护完成, 不崩溃
============================================================
```

---

## Phase 4 验收标准

```python
# Insight Agent
# POST /insights/generate  → 触发手动生成
# → 返回 insight_id, content 非空
# → 下次 GET /insights → 能看到刚生成的洞察

# Memory Manager
# POST /admin/run-maintenance → 触发维护
# → 返回 MaintenanceReport {duplicates_found, new_relations, decayed_memories}
```

### Phase 4 执行记录

| # | 任务 | 日期 | 状态 | 测试结果 |
|---|------|------|------|---------|
| 4.1 | Insight Agent | 2026-06-29 | ✅ | 6 用例通过 + API 端点 /insights/generate + /insights |
| 4.2 | Memory Manager 异步 | 2026-06-29 | ✅ | 8 用例通过（去重/衰减/过期清理/空库）+ API 端点 /admin/run-maintenance |

---

---

# Phase 5: 端到端集成 + 前端对接 ⬜

**目标**: 全链路打通，前端接入新架构，性能优化，文档完善

**依赖**: Phase 4 完成  
**预计周期**: Week 10-12 (3周)

---

### 任务 5.1: API 端点完善

**文件**: `backend/app/api/v1/` (新增/改造)

```
新增端点:
  POST /insights/generate       → 手动触发 Insight Agent
  GET  /insights                → 读取已生成的洞察列表
  POST /admin/run-maintenance   → 手动触发 Memory Manager 维护
  GET  /trajectory/{session_id} → 查看 ReAct 推理轨迹 (调试用)

改造端点:
  POST /qa/ask                  → 响应新增 trajectory_id 字段
  POST /ingest/*                → 摄入后自动触发 Insight Agent (异步)
```

### 任务 5.2: 前端适配

```
前端改造:
  1. AI Chat 页面:
     - 显示来源引用 (sources) 可点击跳转到 Memory Detail
     - 显示 "思考中..." 状态 (Slow 链路时 ReAct 多轮需要时间)
     
  2. Insights 页面 (新):
     - 卡片式展示 AI 生成的洞察
     - 按 insight_type 分类过滤
     
  3. Dashboard:
     - 已接入 Insight 数据 (本周摘要)
     - 显示 Memory Manager 维护状态
     
  4. Memory Detail:
     - 显示关联记忆 (由 RelationFinderTool 自动发现)
     - 显示是否待 Review (由 MemoryWriteTool 标记)
```

### 任务 5.3: 性能优化

```
目标: Fast 链路 < 1.2s, Slow 链路 < 5s (首次)

优化策略:
  1. Router 缓存: 相似问题复用路由结果 (Redis, TTL=5min)
  2. Memory 预加载: WorkingMemory 常驻内存, 不用每次查 DB
  3. LLM 流式输出: Slow 链路使用 streaming 提升体感
  4. 工具并行: ReAct 中独立的检索可以并行执行
```

### 任务 5.4: 文档 + 部署

```
文档:
  1. README.md 更新 → 新架构说明
  2. API 文档 → 所有新增端点
  3. 架构图 → 更新为实际实现状态

部署:
  1. Celery worker 配置 (异步 Insight Agent)
  2. Cron 任务配置 (Memory Manager 定时维护)
  3. 环境变量更新 (.env.example)
```

---

## Phase 5 验收标准

```python
# 全链路验收
# 1. Fast: "你好" → Router → QA Agent → < 1.2s
# 2. Slow: "分析本周学习" → Router → Planner → ReAct → 工具调用 → < 5s
# 3. Insight: 导入10条笔记 → 异步 Insight Agent → Insights 页面可查看
# 4. Memory: Memory Manager 定时执行 → 去重/关联/衰减正常

# 回归清单 (来自 60_测试与验收规范.md)
regression_checklist = [
  "Dashboard 数据正常",
  "Memories CRUD 正常",
  "Todo Center 正常",
  "Timeline 正常",
  "AI Chat 带来源引用",
  "Review Queue 正常",
]
```

### Phase 5 执行记录

| # | 任务 | 日期 | 状态 | 测试结果 |
|---|------|------|------|---------|
| 5.1 | API 端点完善 | - | ⬜ | |
| 5.2 | 前端适配 | - | ⬜ | |
| 5.3 | 性能优化 | - | ⬜ | |
| 5.4 | 文档 + 部署 | - | ⬜ | |

---

---

# 附录 A: 完整调用链路示例 (开发完成后)

## 示例 1: 用户问简单问题 (Fast 链路)

```
用户: "什么是闭包？"
  ↓
API: POST /qa/ask {"question": "什么是闭包？"}
  ↓
QAWorkflow.handle_question()
  ├─ [步骤1] MemoryManager(db, user_id)
  ├─ [步骤2] Router.route("什么是闭包？")
  │   ├─ 读 mm.get_context_for_router()
  │   │   ├─ WorkingMemory: 最近3轮对话 (空)
  │   │   ├─ GoalMemory: 活跃目标 (2个)
  │   │   └─ ProceduralMemory: 待办 (3条)
  │   ├─ 拼 prompt → LLMClient.parse_json()
  │   └─ 返回: {"complexity": "fast", "reason": "简单知识问答"}
  ├─ [步骤3] QA Agent.run()
  │   ├─ _pre_execute: 读记忆上下文
  │   │   ├─ episodic: 最近7天记忆 (15条, 无Python相关)
  │   │   └─ goal: 活跃目标 "三个月掌握后端"
  │   ├─ execute:
  │   │   ├─ 拼 system_prompt (含用户上下文)
  │   │   ├─ LLMClient.chat(messages)
  │   │   └─ 返回: {"status": "success", "data": {"answer": "闭包是...", "sources": []}}
  │   └─ _post_execute:
  │       └─ working.add_turn("user", "什么是闭包？")
  │         working.add_turn("assistant", "闭包是...")
  └─ 返回给 API
  ↓
前端: 显示回答 (无来源引用，因为是通用知识)
```

## 示例 2: 用户问复杂问题 (Slow 链路)

```
用户: "分析我最近一周的学习记录，制定下周学习计划"
  ↓
API: POST /qa/ask {"question": "分析我最近一周的学习记录，制定下周学习计划"}
  ↓
QAWorkflow.handle_question()
  ├─ [步骤1] MemoryManager(db, user_id)
  ├─ [步骤2] Router.route("分析我最近一周的学习记录...")
  │   ├─ 读 mm.get_context_for_router() → 有活跃目标
  │   ├─ LLMClient.parse_json()
  │   └─ 返回: {"complexity": "slow", "reason": "需要多步分析和创建计划",
  │             "suggested_tools": ["hybrid_search", "fact_extractor", "memory_write"]}
  │
  ├─ [步骤3] Planner.create_plan()
  │   ├─ 加载 mm.get_context_for_planner() → 完整上下文
  │   ├─ LLM 拆解:
  │   │   Step 1: hybrid_search(query="学习", time_range="7d")
  │   │   Step 2: fact_extractor(text=$step1_result)
  │   │   Step 3: get_active_goals()
  │   │   Step 4: LLM推理(根据事实+目标生成计划)
  │   │   Step 5: memory_write(title="下周学习计划", content=$step4_result)
  │   └─ 返回: Plan(5 steps)
  │
  ├─ [步骤4] ReAct Agent.run(plan)
  │   Round 1:
  │     Thought: "第一步检索本周学习记录"
  │     Action: hybrid_search(query="学习", time_range="7d")
  │     Observation: 返回 20 条记录
  │   Round 2:
  │     Thought: "从记录中提取学习事实"
  │     Action: fact_extractor(text=$round1_data)
  │     Observation: 提取 12 条事实: Python闭包/FastAPI/Docker...
  │   Round 3:
  │     Thought: "需要对照用户目标"
  │     Action: get_active_goals()
  │     Observation: 目标="三个月掌握后端" 进度 60%
  │   Round 4:
  │     Thought: "数据够了，生成计划"
  │     (纯LLM推理，不调工具)
  │     Observation: "周一复习Python闭包, 周二学FastAPI路由..."
  │   Round 5:
  │     Thought: "写入计划"
  │     Action: memory_write(title="下周学习计划", content=计划文本)
  │     Observation: 写入成功, memory_id=xxx
  │   → 所有步骤完成
  │
  └─ 最终回答:
    "你这周主要学习了 Python闭包、FastAPI、Docker 三个主题。
     距离'三个月掌握后端'目标还有40%未完成。
     已为你创建下周计划(memory_id=xxx)，重点覆盖 API 设计和部署。
     建议: 增加周末实战项目时间来加速学习。"
    sources: [
      {memory_id: "a1", title: "Python闭包笔记"},
      {memory_id: "a2", title: "FastAPI入门"},
      {memory_id: "a3", title: "Docker实践"},
    ]
  ↓
前端: 显示回答 + 来源链接 + "已创建计划"提示
```

## 示例 3: 异步 Insight Agent

```
触发: 用户导入了 15 条新笔记
  ↓
(后台 Celery 任务)
Insight Agent 执行:
  ├─ [步骤1] 读 EpisodicMemory: 最近 7 天记忆
  ├─ [步骤2] 聚类分析:
  │   主题分布: {"机器学习": 8, "Python": 5, "数学": 2}
  │   时间分布: 最活跃 21:00-23:00
  │   连续天数: 连续 12 天有学习记录
  ├─ [步骤3] LLM 生成自然语言洞察:
  │   "你本周学习以机器学习为主(53%)，
  │    集中在晚上9-11点，已连续学习12天。
  │    距'后端开发'目标，建议下周增加API实战内容。"
  ├─ [步骤4] 写入 insights 表:
  │   insight_type="pattern"
  │   content=llm_generated_text
  │   data={"topics": {...}, "streak": 12}
  │   confidence_score=0.88
  └─ 完成
  ↓
下次用户问 "我最近学习状态怎么样？"
  ↓
Fast 路径: QA Agent 读 mm.insights.get_recent(days=7)
  → 直接返回缓存的分析结果，秒回
```

---

# 附录 B: 测试策略总表

```
测试层级:

1. 单元测试 (每个模块独立)
   ├─ Router:           mock LLM，测 10 种输入 → 路由结果正确
   ├─ QA Agent:         mock LLM + mock MemoryManager，测 execute 流程
   ├─ ReAct Agent:      mock LLM + mock ToolRegistry，测循环逻辑
   ├─ Planner:          mock LLM，测计划生成+验证
   ├─ 每个 Tool:        用真实 DB 或 mock API，测核心功能
   └─ Insight Agent:    用测试数据，测分析+写入

2. 集成测试 (串联两个模块)
   ├─ Router + QA Agent:        "你好" → 完整流程 → 返回回答
   ├─ Router + Planner:         "复杂问题" → 生成计划
   ├─ Planner + ReAct Agent:    plan + 模拟工具 → 多轮执行
   ├─ MemoryManager + Tool:     写入→检索→验证
   └─ QAWorkflow + API:         HTTP请求 → 完整链路

3. 端到端测试 (走完整 API)
   ├─ POST /qa/ask (fast)   → 验证回答 + sources + 记忆留存
   ├─ POST /qa/ask (slow)   → 验证 ReAct 轨迹 + 工具调用
   ├─ POST /ingest/url + GET /insights → 验证异步 Insight 生成
   └─ POST /admin/run-maintenance → 验证去重/关联/衰减

4. 回归检查清单 (每次较大改动后)
   □ Dashboard
   □ Memories CRUD
   □ Todo Center
   □ Timeline
   □ AI Chat (带来源引用)
   □ Review Queue
```

---

# 附录 C: 开发规则速查

来自 `docs/standards/` 的关键约束：

```
每次开发:
  1. 一次只处理一个小切片 (不跨模块)
  2. 变更前明确入口文件和受影响模块
  3. 变更后至少做一项验证 (import check / pytest / smoke test)

数据规范:
  4. API 响应统一: {"code": 0, "message": "ok", "data": {}}
  5. 时间字段用 ISO 8601
  6. 所有业务表保留 user_id

AI 规范:
  7. QA 结果必须带引用来源 (sources)
  8. 检索不足时允许回答"不足以判断"
  9. 低置信度操作只做建议，不直接执行 (ReviewQueue)
  10. 禁止无来源的 AI 回答

代码变更:
  11. 优先改最小文件集
  12. 先保证接口和数据结构稳定
  13. 不做无关重构

Definition of Done:
  14. 代码或文档已落盘
  15. 基础验证已通过
  16. 若变更契约，相关文档已同步
```

---

# 附录 D: 文档索引

| 文档 | 路径 | 内容 |
|------|------|------|
| 架构重构计划书 | `docs/architecture_refactor_plan_v1.1_pure_python.md` | 技术选型 + 12周路线图 |
| Phase 0 完成总结 | `docs/phase0_completion_summary.md` | 基础设施搭建记录 |
| Phase 0 启动指南 | `docs/phase0_quickstart.md` | 快速验收 + 核心接口示例 |
| Phase 1 完成总结 | `docs/phase1_completion_summary.md` | 分层记忆重构记录 |
| Phase 2 开发计划 | `docs/phase2_development_plan.md` | Phase 2 单阶段详细计划 |
| 全阶段计划 | `docs/phase_all_development_plan.md` | 本文档 |
| 开发需求基线 | `docs/standards/20_开发需求基线.md` | MVP 范围定义 |
| 技术实现规范 | `docs/standards/30_技术实现规范.md` | 前后端代码规范 |
| 执行步骤与交付 | `docs/standards/50_执行步骤与交付流程.md` | 每日开发切片流程 |
| 测试与验收 | `docs/standards/60_测试与验收规范.md` | 阶段验收标准 |
