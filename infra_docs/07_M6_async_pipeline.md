# M6 — 异步链路上队列（Async Pipeline Hardening）

> 依赖：M1（可观测性）。可与其他 Milestone 并行。
> 目标：把 Insight Agent / Memory Manager 等后台任务，从「同步阻塞 / 手动触发」升级为**队列驱动、可重试、可观测**的异步管线，让写链路（记录）与重活（分析、维护）解耦。

---

## 1. 现状与缺口

现有后台类逻辑（散落在 service 层，非队列驱动）：

| 组件 | 文件 | 现状 | 问题 |
|------|------|------|------|
| Insight Agent | `services/insight_agent_service.py` | 疑似同步调用或手动触发 | 阻塞、无重试、失败即丢 |
| Memory Manager 维护 | `memory/maintenance.py` | 去重/关联/衰减 | 触发时机不明、无调度 |
| Reminder 调度 | `services/reminder_scheduler.py` | 已有调度雏形 | 与其他后台任务各自为政 |
| 记忆分类增强 | `tools/memory/memory_write.py` | AI 分类在写路径同步跑 | 拖慢用户可见的写操作 |

**核心缺口**：
1. 重活跑在**请求线程**里，用户等待时间被 AI 调用拉长。
2. 失败**没有重试**，一次 LLM 抽风就永久丢任务。
3. **无统一调度**：reminder 有自己的 scheduler，insight/maintenance 各搞各的。
4. **不可观测**：后台任务跑没跑、跑多久、失败率多少，全不知道。

`requirements.txt` 已预留 Celery + Redis 的空间（架构文档提及），但尚未接入。

---

## 2. 设计目标

- **写链路瞬时返回**：记录落库后立即返回，AI 增强（分类/标签/摘要）转异步。
- **重活队列化**：Insight 生成、Memory 维护、批量 embedding 走队列。
- **可重试 + 死信**：失败自动重试（指数退避），超限进死信队列，不静默丢。
- **可观测**：每个任务的入队/开始/完成/失败/耗时，接入 M1 的 tracing。
- **降级友好**：Redis / Celery 不可用时，回退到同步执行（保持单机可跑，不破坏现有开发体验）。

---

## 3. 技术选型

| 维度 | 选择 | 理由 |
|------|------|------|
| Broker | Redis | 已在 requirements 规划内，轻量，够用 |
| Worker | Celery | 生态成熟，重试/死信/定时开箱即用 |
| 定时调度 | Celery Beat | 统一 reminder + maintenance 的周期任务 |
| 降级 | `EAGER` 模式 | `CELERY_TASK_ALWAYS_EAGER=True` 时同步执行，本地无需起 Redis |

> **务实取舍**：不引入 Kafka / RabbitMQ 这类重型中间件。个人项目量级下 Redis + Celery 是收益/复杂度最优点，简历上也更容易讲清楚「为什么这么选」。

---

## 4. 目录结构（新增）

```
backend/app/
├── tasks/                          # 🆕 Celery 任务定义
│   ├── __init__.py
│   ├── celery_app.py               # Celery 实例 + 配置（含 EAGER 降级）
│   ├── insight_tasks.py            # 洞察生成任务
│   ├── memory_tasks.py             # 记忆维护 / 异步增强任务
│   └── schedules.py                # Celery Beat 周期任务表
```

---

## 5. 核心实现

### 5.1 Celery 实例（含降级）`tasks/celery_app.py`

```python
"""Celery 应用实例。

关键设计：
- Redis 不可用时通过 CELERY_TASK_ALWAYS_EAGER 降级为同步执行，
  保证本地开发 / CI 不强依赖 Redis。
- 所有任务默认 3 次重试，指数退避，超限进死信。
"""
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "mindmemo",
    broker=settings.redis_url or "memory://",
    backend=settings.redis_url or "cache+memory://",
)

celery_app.conf.update(
    task_always_eager=not bool(settings.redis_url),   # 无 Redis → 同步降级
    task_acks_late=True,                              # 任务完成才确认，防丢
    task_reject_on_worker_lost=True,
    task_default_retry_delay=5,
    task_annotations={
        "*": {"max_retries": 3, "retry_backoff": True, "retry_backoff_max": 60},
    },
    task_track_started=True,
)
```

### 5.2 异步记忆增强 `tasks/memory_tasks.py`

把 `memory_write` 里的 AI 分类/摘要从写路径剥离：

```python
from app.tasks.celery_app import celery_app

@celery_app.task(bind=True, name="memory.enhance")
def enhance_memory(self, memory_id: str):
    """异步增强记忆：AI 分类 + 标签 + 摘要。
    写路径先落最小可用记录并立即返回，本任务后台补全。
    低置信度分类照旧进 ReviewQueue（不变）。
    """
    from app.core.db import SessionLocal
    from app.services.memory_service import memory_service
    with SessionLocal() as db:
        try:
            memory_service.ai_enhance(db, memory_id)   # 复用现有逻辑
        except Exception as exc:
            raise self.retry(exc=exc)                  # 指数退避重试
```

写路径改动（`memory_write.py` / `memory_service`）：

```python
# 改造前：同步 AI 分类（用户等 LLM）
memory = repo.create(...)
memory.category = llm_classify(...)   # ← 阻塞
memory.summary = llm_summarize(...)   # ← 阻塞

# 改造后：先落库返回，增强转异步
memory = repo.create(..., status="enhancing")
enhance_memory.delay(str(memory.id))  # EAGER 模式下等价于同步调用
# 立即返回，前端显示"整理中"，完成后经通知/轮询刷新
```

### 5.3 Insight / 维护 定时任务 `tasks/schedules.py`

```python
from celery.schedules import crontab
from app.tasks.celery_app import celery_app

celery_app.conf.beat_schedule = {
    "nightly-insight": {          # 每晚生成洞察
        "task": "insight.generate_daily",
        "schedule": crontab(hour=3, minute=17),   # 错峰，避开整点
    },
    "memory-maintenance": {       # 记忆去重/关联/衰减
        "task": "memory.maintenance",
        "schedule": crontab(hour=4, minute=23),
    },
}
```
> 沿用现有 `reminder_scheduler` 的语义，把它也收编进 Beat，统一后台调度出口。

---

## 6. 可观测性对接（复用 M1）

每个 Celery 任务包一层，与 `agent_runs` 同源记录：

- 任务入队 → 记 `queued_at`
- 任务开始（`task_track_started`）→ 记 `started_at`
- 完成/失败 → 记 `duration_ms` / `status` / `retries`
- 若任务内部触发 Agent（如 Insight Agent），其 `AgentRun.session_id` 关联回任务 id，形成「任务 → Agent 运行 → LLM 调用」的完整链路。

指标（对接 M3 的 metrics 出口）：
- `task_duration_seconds{task, status}`
- `task_retries_total{task}`
- `task_queue_depth{queue}`

---

## 7. 任务拆解

| # | 任务 | 交付物 | 验收 |
|---|------|--------|------|
| M6-1 | Celery 实例 + EAGER 降级 + Redis 配置 | `celery_app.py` + config 加 `redis_url` | 无 Redis 时同步跑，有 Redis 时异步 |
| M6-2 | 记忆增强转异步 | `enhance_memory` 任务 + 写路径改造 | 写操作 P95 延迟下降（不含 AI） |
| M6-3 | Insight 生成任务化 | `insight_tasks.py` | 手动 `.delay()` 能触发并留痕 |
| M6-4 | 维护任务 + Beat 定时 | `schedules.py` | Beat 按时触发去重/衰减 |
| M6-5 | reminder_scheduler 收编进 Beat | 统一调度出口 | 现有提醒功能不回归 |
| M6-6 | 任务可观测对接 M1 | 任务级 span + 指标 | Grafana/日志能看到任务耗时与失败率 |

---

## 8. 风险与降级

| 风险 | 缓解 |
|------|------|
| Redis 挂了 | EAGER 降级同步执行，功能不中断（只是慢） |
| 异步增强未完成时用户查询 | 记录带 `status=enhancing`，查询侧兼容"整理中"态 |
| 任务重复执行（at-least-once） | 增强任务做幂等：按 `memory_id` 检查是否已增强 |
| Beat 单点 | 个人项目可接受；未来多实例再上分布式锁 |

---

## 9. 与简历的关联（见 `07_resume_narrative.md`）

- 「将 AI 增强、洞察生成、记忆维护等重活从请求线程剥离到 **Celery + Redis 异步管线**，写路径 P95 延迟下降 XX%」
- 「设计 **EAGER 降级**策略，Redis 不可用时无缝回退同步执行，保证本地开发与 CI 零外部依赖」
- 「异步任务与 Agent 轨迹**同源可观测**，构建"任务 → Agent → LLM 调用"的端到端链路追踪」
