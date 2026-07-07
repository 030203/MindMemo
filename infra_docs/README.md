# MindMemo Infra 改造计划

> 把一套"能跑通 demo 的 Agent 系统"升级为"能上线、可观测、可评估、可控成本"的 **LLM Agent 基础设施 (Agent Infra)**。

## 文档索引

| 文档 | 内容 |
|------|------|
| [00_master_plan.md](00_master_plan.md) | 总纲：现状盘点、目标架构、6 期分期、4 个创新点、成功指标、风险边界 |
| [01_current_architecture.md](01_current_architecture.md) | 现状架构详解：真实调用链、三层埋点位置、LLM/轨迹/工具现状 |
| [02_M1_observability.md](02_M1_observability.md) | M1 全链路可观测：Context-Native Tracing + span 埋点 + 轨迹回放 |
| [03_M2_llm_gateway.md](03_M2_llm_gateway.md) | M2 LLM 网关：重试 / 多 provider 故障转移 / 熔断 / 超时分级 |
| [04_M3_cost_metering.md](04_M3_cost_metering.md) | M3 Token / 成本计量与预算熔断 |
| [05_M4_semantic_cache.md](05_M4_semantic_cache.md) | M4 语义缓存层：精确 + 语义两级缓存 |
| [06_M5_eval_harness.md](06_M5_eval_harness.md) | M5 评估闭环：金标准集 + 自动打分 + CI 门禁 + 轨迹重放 |
| [07_M6_async_pipeline.md](07_M6_async_pipeline.md) | M6 异步链路上队列：Celery + Redis，写链路解耦 |
| [08_resume_narrative.md](08_resume_narrative.md) | 简历话术 + 面试深挖故事 + 量化口径 + 忌讳 |

## 一句话定位

MindMemo 已经手写了 Agent 框架（`BaseAgent` 模板方法）、工具系统（`ToolRegistry` + OpenAI function calling）、6 层记忆、两级意图路由（`Router` → `SlowRouter`）、以及 **agent-as-tool 的多智能体协作**（`create_sub_agent` / `mailbox` / `collect_results`）。

本计划**不推倒重来**，而是在此之上补齐让它成为"基础设施"的四根支柱：

1. **可观测性** — 全链路 Tracing（复用已有 `AgentRun` 轨迹表）
2. **可靠性** — LLM Gateway（多 provider 故障转移 + 重试 + 熔断 + 缓存）
3. **可度量** — Token / 成本 / 延迟计量与预算护栏
4. **可评估** — 轨迹级自动化评估闭环（Eval Harness，防 prompt 退化）

## 落地原则

- **痛点驱动、增量交付**：每个 Milestone 独立可验证、可回滚，不阻塞主链路。
- **零侵入优先**：优先在 `llm_answer_service` 和 `BaseAgent.run()` 两个"咽喉点"埋点，避免散弹式改造。
- **测试先行**：沿用项目已有的 pytest 体系（`backend/tests/`），每个能力配回归用例。
