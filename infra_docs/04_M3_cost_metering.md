# M3 — Token / 成本计量与预算控制

> **一句话**：在 LLM 网关埋一个计量点，把每次调用的 token、估算成本、provider、任务类型落库并聚合，实现"按用户 / 按会话 / 按任务类型"的用量可见 + 预算熔断。
>
> **改造对象**：`llm_answer_service._chat_completion*`（埋点）、新增 `app/llm_gateway/metering.py`、新增 `usage_records` 表
> **依赖**：M1（span 关联）、M2（Gateway 是天然埋点位）

---

## 1. 现状缺口

- 现在只有一行 `logger.info(f"LLM使用: {response['usage']}")`（还在死代码 `llm/client.py` 里），真实服务 `llm_answer_service` 连 usage 都没读
- 无法回答：这个用户这个月花了多少？哪类问题最烧 token？多智能体报告一次要几毛钱？
- 无预算控制：一个死循环的 ReAct 可以无限烧钱

---

## 2. 数据模型：usage_records

```python
# app/models/usage_record.py
class UsageRecord(Base, TimestampMixin):
    __tablename__ = "usage_records"
    id: UUID (pk)
    user_id: UUID (index)
    session_id: str (index)          # 关联 AgentRun.session_id
    trace_id: str (index, nullable)  # 关联 M1 的 trace
    agent_name: str                  # react_agent / qa_agent / sub_agent...
    provider: str                    # deepseek / xiaomi
    model: str
    task_class: str                  # routing / user_facing
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float                  # 按价目表估算
    is_failover: bool                # 是否故障转移产生（配合 M2）
    created_at: datetime
```

`session_id` 与已有 `AgentRun` 表对齐 → 一次 agent run 消耗的所有 LLM 调用可聚合。

---

## 3. 埋点位置

在 M2 的 `LLMGateway.call()` 成功返回处统一读取 `response["usage"]`：

```python
# 流式调用（chat_stream）需要单独处理：
# DeepSeek/OpenAI 流式最后一个 chunk 带 usage（需请求时加 stream_options={"include_usage": true}）
# 拿不到时按 tokenizer 估算（tiktoken / 简单字数估算兜底）
```

价目表放 `settings` / 配置文件，按 provider+model 维护每 1K token 的输入/输出单价，`cost_usd = prompt/1000*in_price + completion/1000*out_price`。

---

## 4. 聚合查询（Repo 层）

```python
# app/repos/usage_repo.py
- get_user_usage(user_id, since, until) → 总 token / 总成本
- get_usage_by_task_class(user_id)      → 按 routing/user_facing 分组
- get_usage_by_agent(session_id)        → 单次会话各 agent 消耗
- get_top_expensive_sessions(limit)     → 最烧钱的会话排行
```

---

## 5. 预算熔断（创新点，接 M2）

在 `AgentContext` 增加一个软预算：单次 agent run 的 token 上限。ReAct 主循环每轮结束检查累计 token，超限则提前终止并返回 partial（复用现有 `status=partial` 语义）。

```python
# react_agent.execute 主循环内
if context.get_variable("tokens_used", 0) > MAX_TOKENS_PER_RUN:
    context.add_thought("达到 token 预算上限，提前收敛")
    break  # 走现有 partial 返回路径
```

这把"MAX_ROUNDS 防死循环"升级成"MAX_ROUNDS + token 预算双保险"，是很自然、很能讲的一个可靠性增强。

---

## 6. 暴露方式

- 新增只读 API：`GET /api/v1/admin/usage?user_id=&since=` → 返回聚合结果
- 复用现有前端（可选）：在设置页加一个"用量"卡片
- 对接 M1 dashboard：Grafana/Langfuse 里按 cost 维度出图

---

## 7. 验证方式

1. 单测：mock 一次 usage=（prompt 100, completion 50）→ 落库一条，cost 按价目表算对
2. 单测：聚合查询按 user/session/task_class 分组正确
3. 单测：token 超预算 → ReAct 提前 break，返回 partial
4. 集成：真实跑一次多智能体报告 → usage_records 有多条（coordinator + 各 sub_agent），session 聚合 = 各条之和
5. 流式：chat_stream 能拿到/估算出 usage

---

## 8. 交付物

- `usage_records` 表 + `UsageRecord` 模型 + `usage_repo.py`
- Gateway 埋点 + 价目表配置
- 预算熔断（AgentContext + react_agent）
- 只读用量 API
- 单测 + 集成测试
- `infra_docs/results/M3_*.md`：一次多智能体报告的成本拆解截图/表格
