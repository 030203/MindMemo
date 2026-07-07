"""
Router 路由准确率评测 (v3)
================================
对齐 docs/routing_spec.md v3.0

核心原则：
  - fast = 问候/系统问答 + 外部信息查询（完全不碰用户记录）
  - slow = 默认值，任何可能需要读用户记录的输入

路由纯规则，不调 LLM，评测注入 None 桩也无意义（规则层永远返回结果）。
直接验证规则准确率即可。

运行: cd backend && python -m tests.eval.eval_router_v2
"""
from __future__ import annotations
import os, sys
from collections import defaultdict

_BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


# ────────────────────────────────────────────────────────────────
# 测试集 (input, expected, category, note)
# ────────────────────────────────────────────────────────────────
CASES: list[tuple[str, str, str, str]] = [

    # ════════════════════════════════════════════════════════════
    # FAST 组 A: 系统级交互
    # 特征：问候/告别/询问系统能力，不碰任何记录
    # ════════════════════════════════════════════════════════════
    ("你好",                    "fast", "system",  "基本问候"),
    ("您好",                    "fast", "system",  "尊称问候"),
    ("嗨",                      "fast", "system",  "英文问候"),
    ("hello",                   "fast", "system",  "英文"),
    ("hi",                      "fast", "system",  "英文简写"),
    ("早上好",                  "fast", "system",  "时段问候"),
    ("晚安",                    "fast", "system",  "告别"),
    ("再见",                    "fast", "system",  "告别"),
    ("谢谢",                    "fast", "system",  "道谢"),
    ("感谢你",                  "fast", "system",  "道谢扩展"),
    ("在吗",                    "fast", "system",  "在线询问"),
    ("你是谁",                  "fast", "system",  "系统问答"),
    ("你叫什么",                "fast", "system",  "系统问答"),
    ("你能做什么",              "fast", "system",  "功能询问"),
    ("你能帮我做什么",          "fast", "system",  "功能询问扩展"),
    ("你有什么功能",            "fast", "system",  "功能询问"),
    ("好的",                    "fast", "system",  "确认"),
    ("嗯嗯",                    "fast", "system",  "确认"),
    ("ok",                      "fast", "system",  "英文确认"),
    ("收到",                    "fast", "system",  "确认"),

    # ════════════════════════════════════════════════════════════
    # FAST 组 B: 外部信息查询
    # 特征：答案来自外网 API，不碰用户记录
    # ════════════════════════════════════════════════════════════
    ("北京今天天气怎么样",      "fast", "external", "天气查询"),
    ("明天会下雨吗",            "fast", "external", "天气预报"),
    ("上海气温多少",            "fast", "external", "气温查询"),
    ("今天温度怎么样",          "fast", "external", "温度查询"),
    ("帮我搜一下React教程",     "fast", "external", "网页搜索"),
    ("搜索一下最新的AI新闻",    "fast", "external", "搜索新闻"),
    ("帮我搜最近的iPhone发布",  "fast", "external", "搜索资讯"),
    ("查一下人民币汇率",        "fast", "external", "汇率查询"),
    ("现在几点",                "fast", "external", "时间查询"),
    ("今天几号",                "fast", "external", "日期查询"),
    ("今天是星期几",            "fast", "external", "星期查询"),

    # ════════════════════════════════════════════════════════════
    # SLOW 组 C: 单点查询（涉及个人记录，走 ReAct 单轮）
    # ════════════════════════════════════════════════════════════
    ("我记过妈妈生日吗",                "slow", "lookup",   "生日查询"),
    ("上次那条Docker笔记重点是啥",      "slow", "lookup",   "单条内容回忆"),
    ("那个待办我做完了吗",              "slow", "lookup",   "待办状态确认"),
    ("我有没有记过他的电话",            "slow", "lookup",   "联系人查询"),
    ("上次跑步记了多久",                "slow", "lookup",   "运动记录"),
    ("我上次体重是多少",                "slow", "lookup",   "健康数据"),
    ("上次买的书名叫什么",              "slow", "lookup",   "购买记录"),
    ("我记过那个饭店的地址没",          "slow", "lookup",   "地址查询"),
    ("娃上次打疫苗记了吗",              "slow", "lookup",   "育儿记录"),
    ("上次的药吃完了记得不",            "slow", "lookup",   "健康记录"),
    ("那条关于理财的记录在哪",          "slow", "lookup",   "翻找记录"),
    ("我记没记医保卡号",                "slow", "lookup",   "证件查询"),
    ("我今天记的日记在哪",              "slow", "lookup",   "日记位置"),

    # ════════════════════════════════════════════════════════════
    # SLOW 组 D: 时间罗列（涉及个人记录，走 ReAct 单轮）
    # ════════════════════════════════════════════════════════════
    ("我昨天记了啥",                    "slow", "timelist", "昨日回顾"),
    ("今天有什么记录",                  "slow", "timelist", "今日记录"),
    ("上周有哪些笔记",                  "slow", "timelist", "上周笔记"),
    ("这周记了几篇日记",                "slow", "timelist", "本周计数"),
    ("昨天有什么待办",                  "slow", "timelist", "昨日待办"),
    ("这周的运动记录给我看下",          "slow", "timelist", "本周运动"),
    ("这个月记了多少条笔记",            "slow", "timelist", "笔记数量"),
    ("今天有哪些待办事项",              "slow", "timelist", "今日待办"),
    ("昨天的学习记录",                  "slow", "timelist", "学习日志"),
    ("这周的账记了没",                  "slow", "timelist", "财务记录"),

    # ════════════════════════════════════════════════════════════
    # SLOW 组 E: 分析/规律/趋势
    # ════════════════════════════════════════════════════════════
    ("分析我这个月的学习规律",          "slow", "analysis", "学习规律"),
    ("我最近情绪变化趋势是什么",        "slow", "analysis", "情绪趋势"),
    ("分析一下这段时间的消费结构",      "slow", "analysis", "消费分析"),
    ("我这半年学习效率有提高吗",        "slow", "analysis", "效率趋势"),
    ("看看我这周的运动量达标没",        "slow", "analysis", "运动分析"),
    ("分析我最近的作息规律",            "slow", "analysis", "作息分析"),
    ("分析我这周的时间都花哪了",        "slow", "analysis", "时间分配"),
    ("我最近体重变化有什么规律吗",      "slow", "analysis", "体重趋势"),
    ("评估我这个月的学习效率",          "slow", "analysis", "效率评估"),
    ("盘点一下这个月的开销",            "slow", "analysis", "盘点开销"),

    # ════════════════════════════════════════════════════════════
    # SLOW 组 F: 归纳/总结/提炼
    # ════════════════════════════════════════════════════════════
    ("总结我半年的读书笔记提炼三条",    "slow", "summary",  "读书总结"),
    ("归纳一下我这学期的学习重点",      "slow", "summary",  "学习总结"),
    ("帮我梳理这个项目的关键节点",      "slow", "summary",  "项目梳理"),
    ("提炼一下我这月日记的核心情绪",    "slow", "summary",  "情绪总结"),
    ("归纳我这周学到的新知识",          "slow", "summary",  "知识归纳"),
    ("整理一下我这段时间的灵感想法",    "slow", "summary",  "灵感整理"),
    ("提炼我反复在犯的错误类型",        "slow", "summary",  "错误提炼"),

    # ════════════════════════════════════════════════════════════
    # SLOW 组 G: 对比/评估
    # ════════════════════════════════════════════════════════════
    ("对比我记的两个健身方案",          "slow", "compare",  "健身方案对比"),
    ("比较一下这两个月的学习效果",      "slow", "compare",  "学习效果对比"),
    ("对比这两个项目的难度",            "slow", "compare",  "项目对比"),
    ("比较上个月和这个月的开销",        "slow", "compare",  "月度开销对比"),
    ("对比这两本书的思想核心",          "slow", "compare",  "书籍对比"),

    # ════════════════════════════════════════════════════════════
    # SLOW 组 H: 规划/建议（基于记录）
    # ════════════════════════════════════════════════════════════
    ("根据我的学习记录帮我规划下周",    "slow", "planning", "学习规划"),
    ("我该怎么改进学习方法",            "slow", "planning", "方法改进"),
    ("帮我想想怎么提高效率",            "slow", "planning", "效率建议"),
    ("给我建议一下下一步学什么",        "slow", "planning", "学习建议"),
    ("有什么建议",                      "slow", "planning", "短句建议"),
    ("有什么建议吗",                    "slow", "planning", "短句建议"),
    ("帮我制定一个下月阅读计划",        "slow", "planning", "阅读计划"),
    ("怎么改进我的作息",                "slow", "planning", "作息改进"),
    ("如何提高我的写作频率",            "slow", "planning", "写作建议"),

    # ════════════════════════════════════════════════════════════
    # SLOW 组 I: 复盘/反思
    # ════════════════════════════════════════════════════════════
    ("复盘这次项目失败的原因",          "slow", "review",   "项目复盘"),
    ("反思一下这周为什么效率不高",      "slow", "review",   "效率反思"),
    ("为什么我每次计划都坚持不下去",    "slow", "review",   "坚持反思"),
    ("为啥我总在同一个坑里摔倒",        "slow", "review",   "反复犯错"),
    ("为什么我最近老是失眠",            "slow", "review",   "失眠分析"),

    # ════════════════════════════════════════════════════════════
    # SLOW 组 J: 情绪表达（v3.0 修正：情绪也走 slow，能感知记录背景）
    # ════════════════════════════════════════════════════════════
    ("今天心情不好",                    "slow", "emotion",  "情绪表达"),
    ("最近有点焦虑",                    "slow", "emotion",  "焦虑情绪"),
    ("累死了",                          "slow", "emotion",  "疲惫"),
    ("今天好开心",                      "slow", "emotion",  "开心"),
    ("烦死了",                          "slow", "emotion",  "烦躁"),
    ("有点迷茫",                        "slow", "emotion",  "迷茫"),
    ("感觉最近状态不好",                "slow", "emotion",  "状态感受"),

    # ════════════════════════════════════════════════════════════
    # BOUNDARY: 边界/陷阱用例
    # ════════════════════════════════════════════════════════════
    # B1: 短句，确保默认 slow 而不是误判 fast
    ("帮我分析下",                      "slow", "b-short",  "5字+分析"),
    ("有啥建议",                        "slow", "b-short",  "4字+建议"),
    ("总结一下",                        "slow", "b-short",  "4字+总结"),
    ("最近咋样",                        "slow", "b-short",  "模糊询问→slow"),
    ("我最近怎么样",                    "slow", "b-short",  "自我询问→slow"),

    # B2: 长句但涉及记录 → slow
    ("我今天早上记的那个关于微服务的笔记内容是什么",  "slow", "b-long",  "长句单点检索"),
    ("上次我跟我妈去的那家川菜馆地址记了没",          "slow", "b-long",  "长句查询"),
    ("上周五开会的那条待办还在不在",                  "slow", "b-long",  "长句状态查询"),

    # B3: 容易被误判为 fast 的 slow 用例
    ("查一下我记的那条健身计划",        "slow", "b-trap",   "查一下+个人记录→slow"),
    ("搜一下我有没有记过这个人",        "slow", "b-trap",   "搜一下+个人记录→slow"),
    ("今天心情不好，帮我回顾一下",      "slow", "b-trap",   "情绪+回顾记录→slow"),
    ("天气不错，今天记了几条",          "slow", "b-trap",   "天气+记录→slow"),
]


def run():
    from app.orchestration.router import Router

    router = Router()  # 纯规则，不需要注入桩

    total = len(CASES)
    correct = 0
    errors: list[tuple] = []
    stats: dict[str, dict] = defaultdict(lambda: {"total": 0, "correct": 0})

    fast_count = sum(1 for _, e, _, _ in CASES if e == "fast")
    slow_count = sum(1 for _, e, _, _ in CASES if e == "slow")

    print("=" * 72)
    print("  Router 路由准确率评测 v3")
    print("  对齐 routing_spec.md v3.0 | 纯规则，默认 slow，无 LLM 兜底")
    print(f"  测试集: {total} 条 (fast={fast_count}, slow={slow_count})")
    print("=" * 72)

    for text, expected, cat, note in CASES:
        result = router.route(text)
        stats[cat]["total"] += 1
        is_ok = result.complexity == expected
        if is_ok:
            correct += 1
            stats[cat]["correct"] += 1
        else:
            errors.append((text, expected, result.complexity, note, cat))

    accuracy = correct / total * 100 if total else 0

    print(f"\n  总计: {total} 条  正确: {correct}  准确率: {accuracy:.1f}%\n")

    print("  ── 分类准确率 ──────────────────────────────")
    print(f"  {'类别':<18} {'总量':>4} {'正确':>6} {'准确率':>8}")
    print("  " + "-" * 40)
    for cat in sorted(stats.keys()):
        s = stats[cat]
        acc = f"{s['correct']/s['total']*100:.0f}%" if s['total'] else "-"
        print(f"  {cat:<18} {s['total']:>4} {s['correct']:>6} {acc:>8}")
    print()

    if errors:
        print(f"  ── 错误用例: {len(errors)} 条 ──────────────────")
        for text, expected, actual, note, cat in errors:
            short = text[:38] + "..." if len(text) > 38 else text
            print(f"    [{cat}] {short:<41} 期望={expected:>5} 实际={actual:>5}  ({note})")
        print()

    verdict = "优秀(>=95%)" if accuracy >= 95 else "良好(>=85%)" if accuracy >= 85 else "需调优(<85%)"
    print(f"  结论: {verdict}  准确率: {accuracy:.1f}%")


if __name__ == "__main__":
    run()
