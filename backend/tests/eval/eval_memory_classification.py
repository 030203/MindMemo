"""
记忆分类准确率评测 (MemoryWrite AI 自动分类)

测试集设计：覆盖"可能记录任何事情"的典型场景
  - 学习笔记 / 技术
  - 工作 / 项目
  - 生活 / 日常
  - 情绪 / 心情
  - 灵感 / 想法
  - 健康 / 运动
  - 待办 / 备忘

运行: cd backend && python -m tests.eval.eval_memory_classification
"""
from __future__ import annotations

import asyncio
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


# (标题, 正文, 期望category, 说明)
CASES: list[tuple[str, str, str, str]] = [
    # ── 学习笔记 ────────────────────────────────────
    (
        "闭包学习笔记",
        "今天学习了Python的闭包。闭包是指内部函数引用了外部函数的局部变量，"
        "即使外部函数执行完毕，这些变量仍然被保留。典型用法是装饰器和工厂函数。",
        "学习笔记",
        "技术学习笔记"
    ),
    (
        "《原则》第三章读书笔记",
        "达里奥在这章强调了区分目标和结果的重要性。目标是你想要达成的，"
        "结果是实际发生的。不要因为结果不理想就否定目标，要分析原因。",
        "学习笔记",
        "读书笔记"
    ),
    (
        "英语语法：虚拟语气",
        "虚拟语气表示与事实相反的假设。if条件句：过去式 → would+原形; "
        "had+过去分词 → would have+过去分词。要多做练习巩固。",
        "学习笔记",
        "语言学习"
    ),

    # ── 项目 / 工作 ─────────────────────────────────
    (
        "MindMemo项目架构设计",
        "今天完成了路由层的设计。采用规则+LLM兜底的方式，90%用例走规则，"
        "降低成本。Router → QA Agent → Workflow 三层结构清晰，易测试。",
        "项目",
        "技术项目"
    ),
    (
        "产品评审会纪要",
        "今天下午开了产品评审会，讨论了新功能的优先级。老板决定先做搜索优化，"
        "个性化推荐往后排。下周开始排期，预计两周完成。",
        "项目",
        "工作会议"
    ),

    # ── 想法 / 灵感 ─────────────────────────────────
    (
        "双链笔记可视化想法",
        "突然想到：如果把双链笔记做成知识图谱，节点是笔记，边是引用关系，"
        "可以很直观地看出哪些概念是核心枢纽。可以用D3.js实现交互式可视化。",
        "想法",
        "产品创意"
    ),
    (
        "关于时间管理的思考",
        "今天意识到：不是时间不够，而是精力分配有问题。重要的事要放在精力最好的时候做，"
        "比如早上写代码，下午处理杂事。试试看这周能不能提升效率。",
        "想法",
        "个人思考"
    ),

    # ── 生活 / 日常 ─────────────────────────────────
    (
        "周末去爬山了",
        "今天和朋友去爬了香山，天气不错，人也不多。爬到山顶看日落特别美。"
        "好久没这么放松了，下次要多出来走走。",
        "生活",
        "周末活动"
    ),
    (
        "晚饭吃了新开的川菜馆",
        "公司附近新开了家川菜馆，今天去试了。水煮鱼味道不错，麻辣适中。"
        "就是有点贵，人均100多。偶尔来一次还行。",
        "生活",
        "美食记录"
    ),
    (
        "妈妈生日提醒",
        "妈妈生日是6月15日，提前准备礼物。她最近说想要个按摩椅，"
        "看看618有没有打折的。",
        "生活",
        "家庭备忘"
    ),

    # ── 情绪 / 心情 ─────────────────────────────────
    (
        "今天心情有点低落",
        "不知道为什么，今天一整天都提不起劲。工作也没出什么问题，"
        "就是莫名有点沮丧。可能是天气阴沉的缘故吧。早点睡觉，明天会好的。",
        "生活",  # 情绪日记在分类schema中可能归为"生活"或"其他"
        "情绪记录"
    ),
    (
        "项目上线成功，开心！",
        "今天项目终于上线了，压测也顺利通过，没出大问题。老板还夸了团队。"
        "这段时间的加班总算没白费，成就感满满！",
        "项目",  # 工作相关的情绪可能归到项目
        "工作成就"
    ),

    # ── 健康 / 运动 (分类schema中可能归到"生活"或"其他")───
    (
        "早上跑步5公里",
        "今天早上6点起床去跑步，跑了5公里，用时30分钟。状态很好，"
        "没有之前那种喘不上气的感觉。坚持晨跑一个月了，体重减了3斤。",
        "生活",
        "运动记录"
    ),
    (
        "体检报告",
        "今天拿到体检报告，血压血脂都正常，就是尿酸有点偏高。医生说要少吃海鲜和啤酒，"
        "多喝水多运动。看来得调整饮食了。",
        "生活",
        "健康记录"
    ),

    # ── 备忘 / 待办 ─────────────────────────────────
    (
        "明天开会",
        "明天上午10点有产品评审会，地点在3楼会议室。记得提前准备PPT，"
        "把上周的数据整理一下。",
        "备忘",
        "待办事项"
    ),
    (
        "周五前完成代码review",
        "老板说周五前要把新功能的代码review完，涉及5个PR。"
        "每天抽1小时，应该能按时完成。",
        "备忘",
        "工作待办"
    ),
]


async def run():
    from app.services.llm_answer_service import llm_answer_service

    # 准备一个简单的 LLM client 适配器（parse_json 方法）
    class SimpleLLMClient:
        async def parse_json(self, prompt: str, schema: dict) -> dict | None:
            return llm_answer_service.parse_json(prompt=prompt, schema=schema)

    llm_client = SimpleLLMClient()

    total = len(CASES)
    correct = 0
    wrong_cases = []

    print("=== 记忆分类准确率评测 ===\n")
    print(f"{'标题':<24} {'期望类别':>10} {'实际类别':>10} {'置信度':>8}  {'结果'}")
    print("-" * 70)

    for title, content, expected, desc in CASES:
        # 直接调 LLM 分类（复用 MemoryWrite 的 schema）
        from app.tools.memory.memory_write import _CATEGORY_SCHEMA

        prompt = f"标题: {title}\n\n正文: {content}"
        try:
            result = await llm_client.parse_json(prompt=prompt, schema=_CATEGORY_SCHEMA)
        except Exception:
            result = None

        if result is None:
            actual_category = "解析失败"
            confidence = 0.0
            ok = False
        else:
            actual_category = result.get("category", "未知")
            confidence = result.get("confidence", 0.0)
            ok = (actual_category == expected)

        if ok:
            correct += 1
        else:
            wrong_cases.append((title, expected, actual_category, confidence, desc))

        marker = "[OK]" if ok else "[FAIL]"
        short_title = title[:21] + "..." if len(title) > 21 else title
        print(f"{short_title:<24} {expected:>10} {actual_category:>10} {confidence:>8.2f}  {marker}")

    accuracy = correct / total * 100
    print("-" * 70)
    print(f"\n总计: {total} 条  正确: {correct}  准确率: {accuracy:.1f}%\n")

    if wrong_cases:
        print("── 错误用例 ──────────────────────────────")
        for title, exp, got, conf, desc in wrong_cases:
            print(f"  [{desc}]")
            print(f"    标题: {title}")
            print(f"    期望: {exp}  实际: {got}  置信度: {conf:.2f}")
        print()

    # 统计低置信度比例
    low_conf_count = sum(1 for _, _, _, c, _ in wrong_cases if c < 0.7)
    print(f"低置信度(<0.7)错误: {low_conf_count}/{len(wrong_cases)} "
          f"— 这些会触发 ReviewQueue，用户可介入")
    print()

    print(f"结论: {'优秀(>=85%)' if accuracy >= 85 else '良好(>=70%)' if accuracy >= 70 else '需调优'} ({accuracy:.1f}%)")


if __name__ == "__main__":
    asyncio.run(run())
