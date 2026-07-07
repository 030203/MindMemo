# M2 — LLM 网关：重试 / 故障转移 / 熔断 / 超时分级

> **一句话**：把散落在 `llm_answer_service.py` 里的裸 `urllib` 调用收拢到一个统一的 `LLMGateway`，加上重试、多 provider 故障转移、熔断和按任务分级的超时，让 LLM 调用从"能跑"变成"扛得住抖动"。
>
> **改造对象**：`services/llm_answer_service.py`（核心）、新增 `app/llm_gateway/`
> **删除**：`app/llm/client.py`（死代码，用了废弃的 `openai.error`，无人引用）

---

## 1. 现状缺口（读代码得出）

`llm_answer_service.py` 已经做对的：
- ✅ 多 provider 路由（`routing`=小米 MiMo / `user_facing`=DeepSeek）
- ✅ 小米多 key 轮询（`_next_xiaomi_key`，线程安全）
- ✅ 流式 + function calling

缺的（每一条都是线上会出事的点）：
- ❌ **零重试**：`urlopen` 抛错直接 `return None`，一次网络抖动就丢一次回答
- ❌ **无故障转移**：DeepSeek 挂了不会自动切小米（反之亦然），尽管两个 provider 都配置了
- ❌ **无熔断**：某 provider 持续 5xx 时，仍然每次都去试，拖慢所有请求
- ❌ **超时一刀切**：`llm_request_timeout_seconds` 对"路由判定"和"生成长答案"用同一个值，要么路由太慢要么长答案被切断
- ❌ **key 轮询不感知失败**：某个小米 key 失效了，还是会被轮到

---

## 2. 设计：LLMGateway 包住所有出网调用

```
app/llm_gateway/
├── __init__.py
├── gateway.py         # LLMGateway：重试+转移+熔断的编排
├── breaker.py         # CircuitBreaker：每 provider 一个，三态机
├── policy.py          # RetryPolicy + TimeoutTier（超时分级）
└── errors.py          # 归一化异常：Retryable / Fatal / RateLimited
```

`LLMAnswerService` 的 `_chat_completion*` 内部改为调用 `gateway.call(...)`，**对外接口签名完全不变**（`chat`/`parse_json`/`function_call`/`chat_stream` 全部保留），业务层零改动。

### 2.1 归一化错误分类

```python
# errors.py
class LLMError(Exception): ...
class RetryableError(LLMError): ...   # 5xx / 超时 / 连接重置 → 同 provider 重试
class RateLimitedError(RetryableError): ...  # 429 → 退避更久 + 优先切 key
class FatalError(LLMError): ...       # 4xx(除429) / 认证失败 → 不重试，直接切 provider
```

把 `urllib.error.HTTPError` 的 code 映射进来：`>=500` / timeout → Retryable，`429` → RateLimited，`401/403` → Fatal。

### 2.2 重试 + 故障转移编排

```python
# gateway.py（核心逻辑骨架）
def call(self, *, provider_chain: list[str], build_request, parse_response,
         tier: TimeoutTier):
    """
    provider_chain: 按优先级排列的 provider，如 ["deepseek", "xiaomi"]
    每个 provider 内部按 RetryPolicy 重试，耗尽后转移到下一个 provider。
    """
    last_err = None
    for provider in provider_chain:
        breaker = self._breaker(provider)
        if not breaker.allow():          # 熔断打开，跳过该 provider
            continue
        for attempt in range(self.policy.max_attempts):  # 默认 3
            try:
                resp = self._do_request(provider, build_request, tier.timeout)
                breaker.record_success()
                return resp
            except RateLimitedError as e:
                last_err = e
                self._rotate_key(provider)          # 换 key
                sleep(self.policy.backoff(attempt, jitter=True))
            except RetryableError as e:
                last_err = e
                breaker.record_failure()
                sleep(self.policy.backoff(attempt, jitter=True))
            except FatalError as e:
                last_err = e
                breaker.record_failure()
                break                                # 该 provider 无望，转移
    raise last_err or LLMError("all providers exhausted")
```

### 2.3 熔断器（三态机）

```python
# breaker.py
CLOSED  → 正常放行；连续失败达阈值(默认5) → 转 OPEN
OPEN    → 直接拒绝；经过 cooldown(默认30s) → 转 HALF_OPEN
HALF_OPEN → 放行1个探测请求；成功→CLOSED，失败→OPEN
```

每个 provider 独立一个 breaker，存在进程内（多 worker 各自持有，够用；如需跨 worker 共享可后续挪到 Redis）。

### 2.4 超时分级（TimeoutTier）

| tier | 用途 | 默认超时 | 对应现有调用 |
|------|------|---------|-------------|
| `FAST` | 路由判定 / SlowRouter / JSON 解析 | 8s | `parse_json`, Router |
| `STANDARD` | 普通问答 | 30s | `chat`, `function_call` |
| `LONG` | 报告生成 / 多智能体汇总 | 90s | Multi-Agent 汇总 |

替换掉当前统一的 `settings.llm_request_timeout_seconds`。

---

## 3. provider_chain 的确定

复用现有 `provider_class` 语义，把"单 provider"升级为"provider 链"：

```python
# routing 类任务：小米优先，DeepSeek 兜底
routing:     ["xiaomi", "deepseek"]
# user_facing：DeepSeek 优先，小米兜底
user_facing: ["deepseek", "xiaomi"]
```

链的顺序从 settings 读，保持可配置。故障转移时自动降级到兜底 provider —— 这正好把项目"两个 provider 都配了但只各司其职"的资产利用起来变成高可用。

---

## 4. 与 M1 的联动

Gateway 每次尝试都开一个 llm span（M1），把 `attempt`、`provider`、`breaker_state`、`is_failover=True/False` 写进 span attributes。这样在 trace 里能直接看到"这次回答是 DeepSeek 超时后切到小米才成功的"。

---

## 5. 验证方式

1. 单测：mock 前 2 次抛 RetryableError，第 3 次成功 → `call` 返回成功，共 3 次尝试
2. 单测：provider A 全部失败 → 自动转移到 provider B 成功
3. 单测：连续 5 次失败 → breaker 转 OPEN → 第 6 次直接跳过不发请求
4. 单测：OPEN 状态经过 cooldown → HALF_OPEN → 探测成功 → CLOSED
5. 单测：429 → 触发换 key + 更长退避
6. 集成：真实调用（打断网络模拟）验证故障转移端到端
7. 回归：正常路径下所有现有问答测试通过，接口签名无变化

---

## 6. 交付物

- `app/llm_gateway/` 模块
- `llm_answer_service.py` 内部改造（外部签名不变）
- 删除死代码 `app/llm/client.py`（先确认无引用）
- settings 新增：`llm_retry_max_attempts` / `llm_breaker_threshold` / `llm_timeout_fast|standard|long` / provider_chain 配置
- 单测（覆盖重试/转移/熔断三态/换 key）+ 集成测试
- `infra_docs/results/M2_*.md`：注入故障后的成功率对比（改造前 vs 改造后）
