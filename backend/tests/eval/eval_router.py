"""
Router 路由准确率评测

测试集设计原则：覆盖"可能记录任何事情"定位的各种输入类型
  - 闲聊 / 打招呼
  - 简单问答 / 查事实
  - 记录（笔记/日记/灵感/情绪/健康/待办）
  - 复杂分析 / 规划 / 对比

运行: cd backend && python -m tests.eval.eval_router
"""
from __future__ import annotations

import os
import sys

# 确保 backend 目录在 path 中
_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


# (输入, 期望complexity, 说明)
CASES: list[tuple[str, str, str]] = [
    # ── 闲聊 / 问候 ────────────────────────────────────
    ("你好", "fast", "打招呼"),
    ("今天心情不错", "fast", "情绪表达，短句"),
    ("在吗", "fast", "简单在线询问"),
    ("晚安", "fast", "告别"),

    # ── 简单问答 / 查事实 ───────────────────────────────
    ("Python 中 list 和 tuple 的区别", "fast", "简单技术问答"),
    ("今天几号", "fast", "查日期"),
    ("冥想有什么好处", "fast", "简单知识问答"),
    ("HTTP 和 HTTPS 的区别是什么", "fast", "技术事实问答"),

    # ── 记录类（核心场景）──────────────────────────────
    ("帮我记一下：今天读了《原则》第三章，感受是要区分目标和结果", "fast", "读书笔记记录"),
    ("记录：早上跑步5公里，状态很好", "fast", "健康/运动记录"),
    ("记一下灵感：用双链笔记串联知识点，可以做成可视化图谱", "fast", "灵感记录"),
    ("今天情绪有点低落，不知道为什么，记一下", "fast", "情绪日记记录"),
    ("待办：明天上午10点开产品评审会", "fast", "待办事项"),
    ("备忘：妈妈生日是6月15日", "fast", "个人备忘"),

    # ── 分析 / 规划（slow）────────────────────────────
    ("分析我最近一个月的学习记录，看看哪些知识点反复出现", "slow", "学习记录分析"),
    ("帮我规划下周的学习计划，重点是算法和英语", "slow", "计划制定"),
    ("对比一下我记录的两种健身方案的优缺点", "slow", "对比评估"),
    ("总结我最近半年的读书笔记，提炼出三条核心观点", "slow", "归纳总结"),
    ("复盘这次项目失败的原因，并给出改进建议", "slow", "复盘分析"),
    ("为什么我每次定了计划都坚持不下去，帮我分析", "slow", "行为分析"),

    # ── 边界 / 模糊（slow 或 fast 均可，以标注为准）────
    ("帮我想想这个问题该怎么解决", "slow", "模糊求助，偏分析"),
    ("有什么建议吗", "slow", "开放式建议，偏分析"),
    ("整理一下我的笔记", "slow", "整理类，偏分析"),
]


def run():
    from app.orchestration.router import Router

    router = Router()

    total = len(CASES)
    correct = 0
    wrong_cases = []

    print("=== Router 路由准确率评测 ===\n")
    print(f"{'输入':<36} {'期望':>6} {'实际':>6} {'方式':>8}  {'结果'}")
    print("-" * 70)

    for text, expected, desc in CASES:
        result = router.route(text)
        ok = result.complexity == expected
        if ok:
            correct += 1
        else:
            wrong_cases.append((text, expected, result.complexity, result.decided_by, desc))

        marker = "[OK]" if ok else "[FAIL]"
        short = text[:33] + "..." if len(text) > 33 else text
        print(f"{short:<36} {expected:>6} {result.complexity:>6} {result.decided_by:>8}  {marker}")

    accuracy = correct / total * 100
    print("-" * 70)
    print(f"\n总计: {total} 条  正确: {correct}  准确率: {accuracy:.1f}%\n")

    if wrong_cases:
        print("── 错误用例 ──────────────────────────────")
        for text, exp, got, by, desc in wrong_cases:
            print(f"  [{desc}]")
            print(f"    输入: {text}")
            print(f"    期望: {exp}  实际: {got}  决策方式: {by}")
        print()

    print(f"结论: {'优秀(>=90%)' if accuracy >= 90 else '良好(>=75%)' if accuracy >= 75 else '需调优'} ({accuracy:.1f}%)")


if __name__ == "__main__":
    run()
