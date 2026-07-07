"""
Router 单元测试 (v3.0 对齐)

对齐 routing_spec.md v3.0：
  - fast = 问候/系统问答 + 外部查询（不碰记录）
  - slow = 默认值，任何可能需要读用户记录的输入
  - 纯规则，无 LLM 兜底，Router 永远返回结果
"""
from __future__ import annotations

from app.orchestration.router import Router, RouterResult


class TestFastPath:
    def test_greeting(self):
        r = Router().route("你好")
        assert r.complexity == "fast"
        assert r.decided_by == "rule"

    def test_goodbye(self):
        r = Router().route("再见")
        assert r.complexity == "fast"

    def test_thanks(self):
        r = Router().route("谢谢")
        assert r.complexity == "fast"

    def test_system_who_are_you(self):
        r = Router().route("你是谁")
        assert r.complexity == "fast"
        assert r.decided_by == "rule"

    def test_system_capabilities(self):
        r = Router().route("你能做什么")
        assert r.complexity == "fast"

    def test_weather_query(self):
        r = Router().route("北京今天天气怎么样")
        assert r.complexity == "fast"
        assert "weather" in r.suggested_tools

    def test_web_search(self):
        r = Router().route("帮我搜一下React教程")
        assert r.complexity == "fast"
        assert "web_search" in r.suggested_tools

    def test_date_query(self):
        r = Router().route("今天几号")
        assert r.complexity == "fast"

    def test_empty_input(self):
        r = Router().route("")
        assert r.complexity == "fast"
        assert r.decided_by == "rule"

    def test_ok_confirm(self):
        r = Router().route("ok")
        assert r.complexity == "fast"


class TestSlowPath:
    def test_analysis(self):
        r = Router().route("分析我这个月的学习规律")
        assert r.complexity == "slow"
        assert r.decided_by == "rule"

    def test_summary(self):
        r = Router().route("总结我半年的读书笔记")
        assert r.complexity == "slow"

    def test_planning(self):
        r = Router().route("有什么建议吗")
        assert r.complexity == "slow"

    def test_review(self):
        r = Router().route("复盘一下")
        assert r.complexity == "slow"

    def test_lookup_personal_record(self):
        r = Router().route("我记过妈妈生日吗")
        assert r.complexity == "slow"

    def test_timelist(self):
        r = Router().route("我昨天记了啥")
        assert r.complexity == "slow"

    def test_note_creation_is_slow(self):
        # 记笔记涉及记录操作，走 slow
        r = Router().route("帮我记个笔记：今天学了闭包")
        assert r.complexity == "slow"

    def test_default_fallback_is_slow(self):
        # 没有任何 fast 信号的输入，默认 slow
        r = Router().route("最近怎么样")
        assert r.complexity == "slow"

    def test_long_sentence_default_slow(self):
        r = Router().route("我昨天去了图书馆借了几本关于宋代历史和经济政策方面的书籍想读一读")
        assert r.complexity == "slow"

    def test_emotion_is_slow(self):
        # v3.0: 情绪也走 slow，让 ReAct 感知记录背景
        r = Router().route("今天心情不好")
        assert r.complexity == "slow"

    def test_personal_override_beats_external_query(self):
        # "搜一下" 命中外部查询，但同时有个人域信号 → slow
        r = Router().route("搜一下我有没有记过这个人")
        assert r.complexity == "slow"

    def test_weather_plus_personal_record_is_slow(self):
        # 天气词 + 个人记录词 → slow
        r = Router().route("天气不错，今天记了几条")
        assert r.complexity == "slow"


class TestRouterResultHelpers:
    def test_is_fast(self):
        assert RouterResult(complexity="fast").is_fast is True
        assert RouterResult(complexity="slow").is_fast is False

    def test_is_slow(self):
        assert RouterResult(complexity="slow").is_slow is True
        assert RouterResult(complexity="fast").is_slow is False

    def test_to_dict(self):
        d = RouterResult(complexity="slow", reason="默认", decided_by="rule").to_dict()
        assert d["complexity"] == "slow"
        assert d["reason"] == "默认"
        assert d["decided_by"] == "rule"
        assert "suggested_tools" in d

    def test_suggested_tools_default_empty(self):
        r = RouterResult(complexity="fast")
        assert r.suggested_tools == []

    def test_decided_by_rule_always(self):
        # v3.0：路由器永远由规则决定，不调 LLM
        r = Router().route("分析我的效率")
        assert r.decided_by == "rule"
