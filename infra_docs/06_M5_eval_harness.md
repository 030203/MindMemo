# M5 — 评估闭环（Evaluation Harness）

> 依赖：M1（轨迹已落 `agent_runs`）。可与 M2/M3 并行。
> 目标：把 `tests/eval/` 下的零散脚本，升级为**数据集 + 自动打分 + 回归门禁**的评估闭环，让「改 prompt / 换模型 / 调路由」有可量化的验收标准，杜绝凭感觉调参。

---

## 1. 现状与缺口

`tests/eval/` 现有脚本（散点，无统一入口、无留痕、无门禁）：

| 文件 | 作用 | 问题 |
|------|------|------|
| `eval_router.py` / `eval_router_v2.py` | 路由准确率抽查 | 结果打印到 stdout，跑完即丢 |
| `eval_memory_classification.py` | 记忆分类抽查 | 同上 |
| `e2e_react.py` | ReAct 端到端冒烟 | 无断言阈值 |
| `smoke_xiaomi.py` | provider 连通性 | 手动跑 |

**核心缺口**：
1. 没有**固化的黄金数据集**（golden set），每次评测的样本都不一样，结果不可比。
2. 没有**自动打分**，路由对错靠人眼看 stdout。
3. 没有**历史留痕**，无法回答「这次改动让准确率涨了还是跌了」。
4. 没有**回归门禁**，改坏了不会被拦住。

---

## 2. 设计目标

一句话：**任何一次 prompt / 模型 / 路由逻辑的改动，都能在 1 条命令内得到「改动前 vs 改动后」的量化对比，并在准确率下降时自动拦截。**

评估分三层，对应三条被测链路：

| 层 | 被测对象 | 指标 | 数据来源 |
|----|----------|------|----------|
| L1 路由评估 | `Router` + `SlowRouter` | 分类准确率、混淆矩阵 | 人工标注 golden set |
| L2 工具轨迹评估 | `ReActAgent` 轨迹 | 工具选择正确率、轮数、是否收敛 | golden set + `agent_runs` 回放 |
| L3 答案质量评估 | 端到端答案 | LLM-as-judge 打分（忠实度/相关性/来源引用） | golden set |

---

## 3. 目录结构（新增）

```
backend/
├── eval/                          # 🆕 独立于 tests/，评估是一等公民
│   ├── __init__.py
│   ├── datasets/
│   │   ├── router_golden.jsonl        # 路由黄金集（人工标注）
│   │   ├── slow_router_golden.jsonl   # 二级路由黄金集
│   │   ├── react_trajectory.jsonl     # 工具轨迹黄金集
│   │   └── answer_quality.jsonl       # 答案质量集（含参考答案）
│   ├── scorers/
│   │   ├── __init__.py
│   │   ├── classification.py          # 准确率/召回/混淆矩阵
│   │   ├── trajectory.py              # 工具选择 F1、轮数分布
│   │   └── llm_judge.py               # LLM-as-judge 打分器
│   ├── runners/
│   │   ├── __init__.py
│   │   ├── run_router_eval.py
│   │   ├── run_react_eval.py
│   │   └── run_answer_eval.py
│   ├── reports/                       # 每次评测输出（gitignore，只留 latest 摘要）
│   │   └── {timestamp}_{suite}.json
│   └── run_all.py                     # 统一入口：python -m eval.run_all
```

---

## 4. 数据集格式（JSONL，一行一条）

### 4.1 路由黄金集 `router_golden.jsonl`

```jsonl
{"id": "r001", "question": "你好", "expected": "fast", "tags": ["chitchat"]}
{"id": "r002", "question": "我上周记了哪些跟算法有关的", "expected": "slow", "tags": ["retrieval","time"]}
{"id": "r003", "question": "对比我记的两个健身方案", "expected": "slow", "tags": ["compare"]}
{"id": "r004", "question": "今天北京天气", "expected": "fast", "tags": ["external"]}
```

### 4.2 二级路由黄金集 `slow_router_golden.jsonl`

```jsonl
{"id": "s001", "question": "我昨天记了啥", "expected": "react", "tags": ["single"]}
{"id": "s002", "question": "对比我记的两个健身方案", "expected": "plan", "tags": ["compare"]}
{"id": "s003", "question": "生成我这个月的学习月报", "expected": "multi_agent", "tags": ["report"]}
```

### 4.3 工具轨迹黄金集 `react_trajectory.jsonl`

```jsonl
{"id": "t001", "question": "我记过妈妈生日吗", "expected_tools": ["hybrid_search"], "max_rounds": 2, "must_not_call": ["web_search"]}
{"id": "t002", "question": "帮我把这条简历完整总结一下", "expected_tools": ["hybrid_search","read_memory"], "max_rounds": 3}
{"id": "t003", "question": "我有哪些快到期的待办", "expected_tools": ["list_tasks"], "must_not_call": ["hybrid_search"]}
```
> `must_not_call` 直接编码了当前 system prompt 里「待办必须用 list_tasks，不要用 hybrid_search 猜」这条规则 —— 把 prompt 约定变成可回归的断言。

### 4.4 答案质量集 `answer_quality.jsonl`

```jsonl
{"id": "a001", "question": "我上周学了哪些 Python 内容", "seed_memories": ["mem_fixture_01","mem_fixture_02"], "reference": "闭包、装饰器、异步", "rubric": ["是否引用了真实记录","是否未编造","是否给出来源"]}
```

---

## 5. 打分器设计

### 5.1 分类打分器 `scorers/classification.py`

```python
"""路由类评估：准确率 + 每类 precision/recall + 混淆矩阵。"""
from collections import defaultdict
from dataclasses import dataclass, field

@dataclass
class ClassificationReport:
    total: int
    correct: int
    accuracy: float
    per_label: dict            # {label: {"precision":.., "recall":.., "support":..}}
    confusion: dict            # {(expected, predicted): count}
    failures: list = field(default_factory=list)  # 错例，便于人工复盘

def score_classification(rows: list[dict]) -> ClassificationReport:
    """rows: [{"expected": str, "predicted": str, "id": str, "question": str}]"""
    confusion = defaultdict(int)
    correct = 0
    for r in rows:
        confusion[(r["expected"], r["predicted"])] += 1
        if r["expected"] == r["predicted"]:
            correct += 1
    # ... 计算 per-label precision/recall ...
    failures = [r for r in rows if r["expected"] != r["predicted"]]
    return ClassificationReport(
        total=len(rows), correct=correct,
        accuracy=correct / len(rows) if rows else 0.0,
        per_label=..., confusion=dict(confusion), failures=failures,
    )
```

### 5.2 轨迹打分器 `scorers/trajectory.py`

对每条样本，从 `ReActAgent` 结果的 `context.tool_calls` 提取实际调用的工具序列，与 `expected_tools` 比对：

- **工具集合 F1**：`set(actual) vs set(expected)`
- **禁用工具违规**：`must_not_call ∩ actual` 非空 → 记为硬失败
- **轮数超标**：`rounds > max_rounds` → 记为软失败
- **收敛性**：`status == "partial"`（撞 MAX_ROUNDS）→ 记为未收敛

### 5.3 LLM-as-judge 打分器 `scorers/llm_judge.py`

复用 `llm_answer_service.parse_json`，用一个**独立的、更强的评审 provider**（避免自己判自己）对答案按 rubric 打分：

```python
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "faithfulness": {"type": "integer", "minimum": 1, "maximum": 5},  # 是否忠于记录、无编造
        "relevance":    {"type": "integer", "minimum": 1, "maximum": 5},  # 是否答到点
        "has_source":   {"type": "boolean"},                              # 是否给出来源
        "reason":       {"type": "string"},
    },
    "required": ["faithfulness", "relevance", "has_source"],
}
```
> 关键约束：judge 用 `provider_class` 显式指向与被测模型**不同**的 provider（如被测 DeepSeek、judge 用小米 MiMo），降低同源偏袒。这一点直接利用了 M2 网关的多 provider 能力。

---

## 6. 统一入口与报告

```python
# eval/run_all.py
"""一条命令跑全套评估，输出对比报告。
用法:
    python -m eval.run_all                    # 跑全部，打印摘要
    python -m eval.run_all --suite router     # 只跑路由
    python -m eval.run_all --baseline reports/20260705_router.json  # 与基线对比
"""
```

报告 JSON 结构：

```json
{
  "suite": "router",
  "timestamp": "2026-07-06T16:00:00+08:00",
  "git_sha": "b397638",
  "model": {"routing": "mimo-v2.5", "user_facing": "deepseek-chat"},
  "metrics": {"accuracy": 0.92, "slow_recall": 0.88},
  "vs_baseline": {"accuracy": "+0.04", "verdict": "PASS"},
  "failures": [{"id": "r017", "question": "...", "expected": "slow", "predicted": "fast"}]
}
```

---

## 7. 回归门禁（CI）

`.github/workflows/eval.yml`（或本地 pre-push 钩子）：

```yaml
# 伪代码：评测准确率不得低于基线 - 容差
- run: python -m eval.run_all --suite router --baseline eval/baselines/router.json
  # runner 内部：if accuracy < baseline.accuracy - 0.02: sys.exit(1)
```

门禁规则：
- 路由准确率跌破 `baseline - 2%` → 阻断合并
- 出现 `must_not_call` 违规 → 阻断合并
- LLM-judge 忠实度均分跌破 4.0 → 告警（不阻断，人工复核）

---

## 8. 任务拆解

| # | 任务 | 交付物 | 验收 |
|---|------|--------|------|
| M5-1 | 建 `backend/eval/` 骨架 + JSONL 数据集格式 | 目录 + 4 个数据集文件（各 ≥30 条） | 数据集能被 loader 读取 |
| M5-2 | 分类打分器 + 路由 runner | `run_router_eval.py` | 输出准确率+混淆矩阵+错例 |
| M5-3 | 轨迹打分器 + ReAct runner | `run_react_eval.py` | 输出工具 F1、`must_not_call` 违规数 |
| M5-4 | LLM-judge 打分器 + 答案 runner | `run_answer_eval.py` | 输出三维评分，judge 用独立 provider |
| M5-5 | 统一入口 + 报告留痕 + 基线对比 | `run_all.py` | `--baseline` 能输出 diff |
| M5-6 | CI 门禁 | `eval.yml` | 准确率跌破阈值时 CI 失败 |

---

## 9. 迁移策略

现有 `tests/eval/*.py` 不删除，逐条吸收：
- `eval_router.py` 的样本 → 抽取为 `router_golden.jsonl` 的初始种子
- `eval_router_v2.py` 的判定逻辑 → 并入 `run_router_eval.py`
- `e2e_react.py` → 升级为 `run_react_eval.py`，补 `expected_tools` 断言
- 吸收完成后，旧脚本标记 `# DEPRECATED: 见 eval/`，保留一个版本周期再删

---

## 10. 与简历的关联（见 `07_resume_narrative.md`）

- 「从零搭建 LLM 应用的**离线评估体系**，覆盖路由分类 / 工具调用轨迹 / 答案质量三层，支持黄金集回归与 CI 门禁」
- 「引入 **LLM-as-judge** 并用**异源评审**（评审模型与被测模型分离）降低同源偏袒」
- 「把 system prompt 里的软约定（如"待办查询禁用语义搜索"）编码为 `must_not_call` **可回归断言**，防止 prompt 迭代引入回归」
