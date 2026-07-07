# Phase 2 开发计划 — 工具系统构建 + 详细流程注释

**日期**: 2026-06-25  
**依赖**: Phase 0 基础设施 + Phase 1 分层记忆 → 两者均已完成  
**状态**: ⬜ 待开始  
**预计周期**: Week 4-5 (2周)

---

## 一、当前进度总览

```
✅ Phase 0: 基础设施搭建
   BaseAgent / BaseTool / ToolRegistry / MemoryManager / LLMClient
   40 个测试用例通过

✅ Phase 1: 分层记忆重构  
   goals / insights / memory_goal_links 表创建
   6 层 Memory 全部补全实现 (对接真实 repository)
   GoalRepository + InsightRepository
   79 passed / 8 skipped

⬜ Phase 2: 工具系统构建  ← 当前阶段
   7 个具体工具实现 + 注册到 ToolRegistry
   router / qa_agent / qa_workflow (基础编排)

⬜ Phase 3: 编排层完���
   Planner + ReAct Agent + Insight Agent + Memory Manager 异步

⬜ Phase 4: 端到端集成 + 前端对接
```

---

## 二、Phase 2 目标

把 ToolRegistry 从"空壳"填充为"7 个 Agent 可调用的具体工具"，
然后实现 Router + QA Agent，把 Phase 0 的骨架串成第一条可用的 Fast 链路。

### 2.A 工具系统 — 三大类共 7 个工具

```
tools/
├── retrieval/                  # 检索工具 (3个)
│   ├── hybrid_search.py        # 混合检索: 关键词 + 语义
│   ├── time_resolver.py        # 时间表达式解析: "上周" → 日期范围
│   └── fact_extractor.py       # 事实提取: 文本 → 结构化事实
├── memory/                     # 记忆工具 (2个)
│   ├── relation_finder.py      # 关系发现: 两条记忆之间的关联
│   └── memory_write.py         # 记忆写入: Agent 自主创建记忆
└── external/                   # 外部工具 (2个)
    ├── web_search.py           # 网络搜索 (Tavily API)
    └── weather.py              # 天气查询 (OpenWeather API)
```

### 2.B 编排层 — Fast 链路跑通

```
orchestration/
├── router.py                   # 意图分析 + 路由决策
└── qa_workflow.py              # QA 工作流编排

agent/
└── qa_agent.py                 # QA Agent (BaseAgent 子类)
```

---

## 三、详细任务清单 + 实现流程

每个工具都标注了完整的内部处理流程，开发时严格按步骤实现，测试时对着"测试要点"逐条验证。

---

### 任务 2.1：HybridSearchTool

**文件**: `backend/app/tools/retrieval/hybrid_search.py`  
**依赖**: MemoryManager (EpisodicMemory + SemanticMemory)  
**预计**: 0.5天

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

---

### 任务 2.2：TimeResolverTool

**文件**: `backend/app/tools/retrieval/time_resolver.py`  
**依赖**: LLMClient (兜底解析)  
**预计**: 0.5天

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  time_expression: str  # "上周", "本月", "2024年3月", "最近一周"

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
  如果步骤2无法匹配:
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
      "confidence": 0.95,  # 规则=1.0, LLM=实际值
      "resolution_method": "rule" | "llm"
    }
  )

============================================================
测试要点:
  1. "今天" → 正确日期范围
  2. "上周" → 周一~周日
  3. "最近3天" → 3天前~今天
  4. "去年三月" → LLM兜底, confidence < 1.0
  5. 非法输入: "香蕉" → success=False, error="无法解析"
============================================================
```

---

### 任务 2.3：FactExtractorTool

**文件**: `backend/app/tools/retrieval/fact_extractor.py`  
**依赖**: LLMClient.parse_json  
**预计**: 0.5天

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
  调 LLMClient.parse_json(
    prompt=text,
    schema={
      "type": "object",
      "properties": {
        "facts": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "subject": {"type": "string"},
              "predicate": {"type": "string"},
              "object": {"type": "string"},
              "confidence": {"type": "number"}
            }
          }
        }
      }
    }
  )

[步骤4] 后处理 + 去重
  - 去重: 相同 (subject, predicate, object) 只保留 confidence 最高的
  - 按 confidence 降序

[步骤5] 返回 ToolResult
  ToolResult(
    success=True,
    data={
      "facts": [
        {"subject": "用户", "predicate": "学习了", "object": "Python闭包", "confidence": 0.95},
        ...
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

### 任务 2.4：RelationFinderTool

**文件**: `backend/app/tools/memory/relation_finder.py`  
**依赖**: MemoryManager (SemanticMemory + EpisodicMemory)  
**预计**: 0.5天

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  memory_id: UUID               # 源记忆ID
  max_relations: int = 10       # 最多返回几条关系

[步骤2] 获取源记忆详情
  调用 mm.episodic.get_by_id(memory_id)
  提取 tags / keywords / entities / category / time_info

[步骤3] 多维相似度匹配
  [3.1] 标签重叠: 两条记忆共享 tags 越多 → 分数越高
  [3.2] 关键词重叠: 共享 keywords 的 Jaccard 相似度
  [3.3] 实体重叠: 共享 entities (人名/地名/技术名)
  [3.4] 时间接近: event_time 在 24h 内的记忆 → 加分
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
        {
          "target_memory_id": "uuid-yyy",
          "score": 0.85,
          "overlap_fields": ["tags", "keywords"],
          "explanation": "共享 3 个标签: Python, 编程, 学习"
        },
        ...
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

---

### 任务 2.5：MemoryWriteTool

**文件**: `backend/app/tools/memory/memory_write.py`  
**依赖**: MemoryService / memory_repository  
**预计**: 1天

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  title: str           # 标题
  content: str         # 正文
  category: str = None # 类别 (笔记/想法/待办/...)
  tags: list[str] = [] # 标签
  source: str = "agent" # 来源标记

[步骤2] 内容清洗
  调用 content_clean = 去HTML/去多余空格/截断过长内容

[步骤3] AI 增强 (可选，轻量)
  如果 category 为空 → 调 LLM 自动分类
  如果 tags 为空 → 调 LLM 自动提取标签/关键词
  生成 content_summary (不超过 200 字)

[步骤4] 写入数据库
  调用 memory_repository.create()

[步骤5] 触发 ReviewQueue (低置信度保护)
  如果 AI 自动分类置信度 < 0.7:
    创建 ReviewQueue 条目: "请确认这条记忆的分类和标签"
  目的: 防止 AI 乱分类污染记忆库
  (对齐规范: "不允许做成黑盒自动修改核心用户数据")

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
      "needs_review": False  # 是否需要用户确认
    }
  )

============================================================
测试要点:
  1. 完整写入: title+content+category+tags → 成功入库
  2. 自动分类: category 为空 → AI 自动分类 → 入库
  3. ReviewQueue触发: 低置信度 → needs_review=True
  4. 空标题: title="" → success=False
  5. 超长内容: 3000字 → 自动截断 + 摘要
============================================================
```

---

### 任务 2.6：WebSearchTool

**文件**: `backend/app/tools/external/web_search.py`  
**依赖**: Tavily API (或其它搜索 API)  
**预计**: 0.5天

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  query: str              # 搜索关键词
  max_results: int = 5    # 返回结果数

[步骤2] 调用搜索 API
  调用 Tavily API (或 fallback 到其它搜索引擎)
  超时时间: 5s
  重试: 最多 2 次

[步骤3] 结果格式化
  每条结果提取: title / url / snippet / published_date

[步骤4] 返回 ToolResult
  ToolResult(
    success=True,
    data={
      "results": [
        {"title": "...", "url": "...", "snippet": "...", "published_date": "..."},
        ...
      ],
      "query": "Python闭包",
      "total_results": 5
    }
  )

============================================================
测试要点:
  1. 正常搜索: "Python" → 返回结果列表
  2. API不可用: → success=False, 有错误信息, 不崩溃
============================================================
```

---

### 任务 2.7：WeatherTool

**文件**: `backend/app/tools/external/weather.py`  
**依赖**: OpenWeather API  
**预计**: 0.5天

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  city: str              # 城市名
  date: str = "today"    # 日期 (today/tomorrow/ISO date)

[步骤2] 日期解析
  如果 date 不是 ISO 格式:
    调用 TimeResolverTool 解析

[步骤3] 调用天气 API
  调用 OpenWeather API
  超时: 5s

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

## 四、编排层 — Fast 链路

### 任务 2.8：Router (意图路由)

**文件**: `backend/app/orchestration/router.py`  
**依赖**: LLMClient + MemoryManager  
**预计**: 1天

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
  目的: 路由决策不能只看当前问题，还要结合上下文
    例: 用户刚说"帮我分析学习记录"，下一句"那Python呢？"
    只看"那Python呢？"会误判为简单问题

[步骤3] 构造路由 Prompt
  将步骤2的上下文 + 用户消息拼成路由 prompt:
  
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
  
  返回 JSON: {"complexity": "fast"|"slow", "reason": "分类理由", "suggested_tools": []}
  '''
  
  user_prompt = f"用户输入: {user_message}"

[步骤4] 调 LLM 做分类
  调用 LLMClient.parse_json(
    prompt=user_prompt, 
    system_message=system_prompt, 
    schema=ROUTER_SCHEMA
  )
  
  ROUTER_SCHEMA = {
    "type": "object",
    "properties": {
      "complexity": {"type": "string", "enum": ["fast", "slow"]},
      "reason": {"type": "string"},
      "suggested_tools": {"type": "array", "items": {"type": "string"}}
    },
    "required": ["complexity", "reason"]
  }

[步骤5] 返回路由结果
  RouterResult:
    - complexity: "fast" | "slow"
    - reason: str
    - suggested_tools: list[str]

[步骤6] 记录路由日志
  将路由结果写入 AgentContext.metadata["router_decision"]

============================================================
测试要点:
  1. "你好" → fast
  2. "帮我记个笔记" → fast  
  3. "分析最近一个月的学习记录并制定下周计划" → slow
  4. 连续上下文: 先问"最近学了什么"再问"那Django呢" → slow (依赖上下文)
============================================================
```

---

### 任务 2.9：QA Agent (Fast 路径)

**文件**: `backend/app/agent/qa_agent.py`  
**依赖**: BaseAgent + ToolRegistry + MemoryManager  
**预计**: 1天

```
============================================================
内部处理流程:
============================================================

[步骤1] 接收输入 (由父类 BaseAgent.run() 调用)
  input_data = {
    "question": "用户问题原文",
    "router_result": {
      "complexity": "fast",
      "reason": "简单问答",
      "suggested_tools": []
    }
  }

[步骤2] _pre_execute — 加载记忆上下文
  从 MemoryManager 加载:
    - working.get_recent_turns(n=5) → 最近 5 轮对话
    - episodic.get_recent_memories(days=7, limit=5) → 最近一周记忆
    - semantic.search_by_keywords(question_keywords) → 相关语义记忆
  目的: 让 LLM 回答时"知道"用户的历史和偏好
  例: 用户问"我昨天学了什么？"，需要从 episodic 拿到昨天的记录
  
  将加载的上下文存储到 context.variables:
    context.variables["working_context"] = recent_turns
    context.variables["episodic_context"] = recent_memories
    context.variables["semantic_context"] = related_facts

[步骤3] execute — 构造 Prompt + 调 LLM
  [3.1] 拼装 system prompt
    system_prompt = f'''你是 MindMemo，一个个人记忆助手。
    
    用户信息:
    - 活跃目标: {goals}
    - 最近记忆: {recent_memories}
    
    对话历史:
    {conversation_history}
    
    回答规则:
    1. 基于用户记忆回答问题，优先引用记忆中的信息
    2. 如果问题与记忆无关，当做通用知识问答
    3. 回答简洁，不要编造记忆中没有的信息
    4. 如果用户说"记下来"、"帮我记"，请调用 save_memory 工具
    '''
  
  [3.2] 拼装 user message
    messages = [
      {"role": "system", "content": system_prompt},
      *conversation_history,
      {"role": "user", "content": question}
    ]
  
  [3.3] 判断是否需要工具
    如果 suggested_tools 非空或有记忆操作意图:
      → 使用 LLMClient.chat(messages, functions=available_tools)
      → 如果 LLM 返回 function_call，调用 _call_tool() 执行
      → 将工具结果追加到 messages，再调一次 LLM 生成最终回答
    否则:
      → 使用 LLMClient.chat(messages) 直接生成回答
  
  [3.4] 返回结果
    return {
      "status": "success",
      "data": {
        "answer": "LLM 的回答文本",
        "sources": [{"memory_id": "xxx", "title": "Python笔记", "relevance": 0.9}],
        "tool_calls_made": []
      }
    }

[步骤4] _post_execute — 写回记忆
  [4.1] 更新 WorkingMemory
    working.add_turn("user", question)
    working.add_turn("assistant", answer)
  
  [4.2] 记录到 EpisodicMemory
    将此轮 QA 写入 memory_items 表 (如果值得记录)
    判断标准: 问题涉及用户个人数据、有实质性内容
    闲聊如"你好"、"谢谢"可以不记
  
  [4.3] 记录 QA 日志
    写入 qa_logs (用于统计分析)

============================================================
测试要点:
  1. 简单知识问答: "什么是闭包？" → 直接 LLM 回答
  2. 记忆查询: "我昨天学了什么？" → 查 episodic → LLM 回答
  3. 带工具调用: "帮我记个笔记" → 调 MemoryWriteTool
  4. 对话连续性: 连续问3个问题，检查 working memory 是否正确传递
============================================================
```

---

### 任务 2.10：QAWorkflow (编排)

**文件**: `backend/app/orchestration/qa_workflow.py`  
**依赖**: Router + QA Agent  
**预计**: 0.5天

```
============================================================
内部处理流程:
============================================================

[步骤1] 入口: handle_question(db, user_id, question)
  这是外部 API 调用的唯一入口

[步骤2] 初始化 MemoryManager
  mm = MemoryManager(db, user_id)

[步骤3] 初始化 Router
  router = Router(llm_client=LLMClient())

[步骤4] 路由决策
  # === 意图分析 ===
  router_result = await router.route(
    message=question,
    memory_manager=mm,
    db=db,
    user_id=user_id
  )
  # router_result = {"complexity": "fast", "reason": "...", "suggested_tools": []}

[步骤5] 分支执行
  [分支5A] Fast 路径:
    if router_result.complexity == "fast":
      agent = QAAgent(
        name="qa_agent",
        memory_manager=mm,
        tool_registry=registry  # 包含 7 个工具
      )
      result = await agent.run(
        db=db, user_id=user_id,
        input_data={"question": question, "router_result": router_result}
      )

  [分支5B] Slow 路径 (Phase 3 实现):
    elif router_result.complexity == "slow":
      # TODO Phase 3: Planner → ReAct Agent
      pass  # 暂时 fallback 到 QA Agent

[步骤6] 写回 WorkingMemory
  mm.working.add_turn("user", question)
  mm.working.add_turn("assistant", result["data"]["answer"])

[步骤7] 返回给 API 层
  return result

============================================================
测试要点 (集成测试):
  1. Fast 链路: "你好" → router="fast" → QA Agent → 返回回答
  2. Slow 降级: 复杂问题 → Phase 3 前降级为 QA Agent
  3. 记忆留存: 问完后再问"刚才问了什么"，能查到 working memory
  4. 错误处理: LLM 挂了 → 返回友好错误，不要 500
============================================================
```

---

### 任务 2.11：接入 API 端点

**文件**: `backend/app/api/v1/qa.py` (改造)  
**依赖**: QAWorkflow  
**预计**: 0.5天

```
============================================================
改造内容:
============================================================

[改造前] qa_service.py 直接调 llm_answer_service.chat()
[改造后] qa_service.py 调 qa_workflow.handle_question()

变更:
  1. POST /qa/ask 现在走 Router → QA Agent → LLM (带记忆上下文)
  2. 响应格式新增 sources 字段 (引用来源)
  3. 自动记录对话到 WorkingMemory

保留兼容:
  - 请求/响应 Pydantic schema 不变 (SimpleQARequest / SimpleQAResponse)
  - LLM 不可用时返回友好错误消息
============================================================
```

---

## 五、完成标志

### Phase 2.A 完成 (工具系统)

- [ ] 7 个工具全部注册到 ToolRegistry
- [ ] 每个工具的 `to_json_schema()` 符合 OpenAI Function Calling 规范
- [ ] 24+ 个单元测试全部通过

```python
# 验收代码
registry = ToolRegistry()
registry.register(HybridSearchTool)
registry.register(TimeResolverTool)
registry.register(FactExtractorTool)
registry.register(RelationFinderTool)
registry.register(MemoryWriteTool)
registry.register(WebSearchTool)
registry.register(WeatherTool)
assert len(registry.list_tool_schemas()) == 7
```

### Phase 2.B 完成 (Fast 链路)

- [ ] `POST /qa/ask` 走完整 Router → QA Agent → LLM 链路
- [ ] 回答带记忆上下文 (能引用用户的历史记忆)
- [ ] 回答带来源引用 (sources 非空)
- [ ] 对话历史正确记录到 WorkingMemory
- [ ] 6+ 个集成测试全部通过

---

## 六、任务依赖图

```
2.1 HybridSearch ──┐
2.2 TimeResolver   ├──→ 2.8 ToolRegistry集成 ──→ 2.9 QA Agent
2.3 FactExtractor  │                                    │
2.4 RelationFinder │                                    ▼
2.5 MemoryWrite   ─┘                              2.10 QAWorkflow
2.6 WebSearch     ─┐                                    │
2.7 Weather       ─┘                                    ▼
                                                  2.11 API接入
                                                      │
                                                      ▼
                                                  Phase 2.END
```

---

## 七、执行记录

按 `docs/standards/50_执行步骤与交付流程.md` 规范，每完成一个切片记录到下方：

| # | 任务 | 日期 | 状态 | 测试结果 | 备注 |
|---|------|------|------|---------|------|
| 2.1 | HybridSearch | - | ⬜ | - | |
| 2.2 | TimeResolver | - | ⬜ | - | |
| 2.3 | FactExtractor | - | ⬜ | - | |
| 2.4 | RelationFinder | - | ⬜ | - | |
| 2.5 | MemoryWrite | - | ⬜ | - | |
| 2.6 | WebSearch | - | ⬜ | - | |
| 2.7 | Weather | - | ⬜ | - | |
| 2.8 | ToolRegistry集成 | - | ⬜ | - | |
| 2.9 | QA Agent | - | ⬜ | - | |
| 2.10 | QAWorkflow | - | ⬜ | - | |
| 2.11 | API接入 | - | ⬜ | - | |

---

## 八、开发规则 (来自 docs/standards/)

1. **每次只处理一个小切片** — 不要一次同时推进多个工具
2. **变更前明确入口文件和受影响模块**
3. **变更后至少执行一项验证**: build / import check / API smoke test
4. **QA 结果必须带引用来源** — 对齐 "AI 与 RAG 规范"
5. **低置信度操作只做建议，不直接执行** — 对齐 "不允许黑盒修改数据"
6. **每个工具标注 created_by="agent"** — 对齐 "不允许无来源的 AI 回答"
