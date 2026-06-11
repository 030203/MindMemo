from __future__ import annotations

from pathlib import Path
import sys
import unittest
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models import Base  # noqa: E402
from app.models.memory import MemoryItem  # noqa: E402
from app.models.user import User, UserSetting  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.schemas.qa import QARequest  # noqa: E402
from app.services.chunk_service import chunk_service  # noqa: E402
from app.services.llm_answer_service import llm_answer_service  # noqa: E402
from app.services.qa_service import qa_service  # noqa: E402
from app.services.query_router_service import query_router_service  # noqa: E402


class ContextStrategyQATest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        self.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        self.db = self.SessionLocal()
        self.user_id = uuid.uuid4()
        self.db.add(
            User(
                id=self.user_id,
                email=f"context-{self.user_id}@example.com",
                password_hash="not-used",
                display_name="Context Tester",
                status="active",
            )
        )
        self.db.add(
            UserSetting(
                user_id=self.user_id,
                timezone="Asia/Shanghai",
                language="zh-CN",
                notify_channels=["in_app"],
                llm_provider="local",
                llm_model="none",
                auto_tag_enabled=True,
                auto_summary_enabled=True,
                web_search_enabled=False,
            )
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()

    def _create_memory(self, title: str, content: str, *, source_type: str = "memo", category: str = "memo") -> MemoryItem:
        memory = MemoryItem(
            user_id=self.user_id,
            source_type=source_type,
            title=title,
            content_raw=content,
            content_clean=content,
            content_summary=content[:180],
            category=category,
            tags=[],
            keywords=[],
            entities=[],
            time_info={},
            importance_score=0.5,
            confidence_score=0.8,
            status="active",
            created_by="user",
        )
        self.db.add(memory)
        self.db.flush()
        chunk_service.rebuild_chunks_for_memory(self.db, memory)
        self.db.commit()
        self.db.refresh(memory)
        return memory

    def test_full_summary_current_record_covers_entire_day(self) -> None:
        memory = self._create_memory(
            "周一流水账",
            (
                "早上 7 点起床，吃了早餐，整理书包，还确认了今天的课程安排。"
                "上学路上坐公交，到了学校先交数学作业，然后上午主要上语文和英语。"
                "放学后去操场等同学，一起讨论了科学展板，还记下明天要带彩纸。"
                "晚上回家吃饭，复习英语单词，睡前把书包和校服都准备好了。"
            ),
        )

        response = qa_service.answer_question(
            self.db,
            self.user_id,
            QARequest(
                question="总结这一天",
                active_record_id=str(memory.id),
                active_context_type="record",
            ),
        )

        self.assertIn("早上", response.answer)
        self.assertIn("上学", response.answer)
        self.assertIn("放学", response.answer)
        self.assertIn("晚上", response.answer)
        self.assertEqual(response.trace.metadata["context_strategy"], "full_summary")
        self.assertTrue(response.trace.metadata["context_strategy_debug"]["triggered_full_summary"])

    def test_detail_qa_retrieves_only_inside_current_file(self) -> None:
        target = self._create_memory(
            "合同 A.pdf",
            "合同 A 的付款安排是首款 1000 元。若逾期交付，违约金是 500 元，并且需要书面通知。",
            source_type="pdf",
        )
        other = self._create_memory(
            "合同 B.pdf",
            "合同 B 的违约金是 999 元，交付地点在北京。",
            source_type="pdf",
        )

        response = qa_service.answer_question(
            self.db,
            self.user_id,
            QARequest(
                question="违约金是多少？",
                active_doc_id=str(target.id),
                active_context_type="document",
            ),
        )

        self.assertIn("500", response.answer)
        self.assertNotIn("999", response.answer)
        self.assertEqual(response.trace.metadata["context_strategy"], "local_qa")
        self.assertTrue(response.trace.candidates)
        self.assertEqual({candidate.memory_id for candidate in response.trace.candidates}, {str(target.id)})
        self.assertNotEqual(str(other.id), response.citations[0].id)

    def test_exhaustive_extract_scans_all_chunks(self) -> None:
        memory = self._create_memory(
            "项目会议纪要",
            (
                "开场确认待办：需要整理需求清单，并在周三前发给产品。"
                "中间讨论架构方案，记录了缓存、队列和部署方式。"
                "最后确认待办：联系法务检查合同条款，还要补一份上线回滚预案。"
            ),
        )
        chunk_count = len(chunk_service.ensure_chunks_for_memory(self.db, memory))

        response = qa_service.answer_question(
            self.db,
            self.user_id,
            QARequest(
                question="列出所有待办",
                active_record_id=str(memory.id),
                active_context_type="record",
            ),
        )

        self.assertIn("整理需求清单", response.answer)
        self.assertIn("联系法务", response.answer)
        self.assertEqual(response.trace.metadata["context_strategy"], "exhaustive_extract")
        debug = response.trace.metadata["context_strategy_debug"]
        self.assertEqual(debug["retrieved_chunk_ids"], [])
        self.assertEqual(len(debug["expanded_chunk_ids"]), chunk_count)
        self.assertTrue(debug["triggered_exhaustive_extract"])

    def test_selected_text_is_used_directly(self) -> None:
        response = qa_service.answer_question(
            self.db,
            self.user_id,
            QARequest(
                question="解释这段",
                selected_text="这句话说缓存预热会降低首屏等待，但会增加发布前的准备时间。",
            ),
        )

        self.assertIn("缓存预热", response.answer)
        self.assertEqual(response.trace.metadata["context_strategy"], "direct_selected_text")
        debug = response.trace.metadata["context_strategy_debug"]
        self.assertEqual(debug["retrieved_chunk_ids"], [])

    def test_current_file_question_does_not_recall_other_file(self) -> None:
        target = self._create_memory(
            "交付说明 A.txt",
            "当前文件说明：交付地点在上海，交付联系人是林工，验收材料需要纸质盖章。",
            source_type="file",
        )
        other = self._create_memory(
            "交付说明 B.txt",
            "另一个文件说明：交付地点在北京，交付联系人是周工。",
            source_type="file",
        )

        response = qa_service.answer_question(
            self.db,
            self.user_id,
            QARequest(
                question="交付地点在哪里？",
                active_doc_id=str(target.id),
                active_context_type="document",
            ),
        )

        self.assertIn("上海", response.answer)
        self.assertNotIn("北京", response.answer)
        self.assertEqual({candidate.memory_id for candidate in response.trace.candidates}, {str(target.id)})
        self.assertNotEqual(str(other.id), response.citations[0].id)

    def test_inline_context_summary_fallback_does_not_only_use_opening(self) -> None:
        content = (
            "早上六点四十分，小明被闹钟叫醒。"
            "六点五十五分，他来到餐桌前吃早餐。"
            "上午到学校后，他交了作业并参加了语文课。"
            "放学后他和同学讨论科学展板，还记录了明天要带彩纸。"
            "晚上回家后，他复习英语单词并整理了第二天的书包。"
        )

        response = qa_service.answer_question(
            self.db,
            self.user_id,
            QARequest(
                question="小明这一天总结一下啊",
                context_title="小明的一天",
                context_text=content,
            ),
        )

        self.assertIn("早上", response.answer)
        self.assertIn("学校", response.answer)
        self.assertIn("放学", response.answer)
        self.assertIn("晚上", response.answer)

    def test_full_summary_repairs_coverage_without_chunk_listing(self) -> None:
        memory = self._create_memory(
            "RAG Agent 项目复盘",
            (
                "2026年3月到2026年5月期间，项目组推进个人知识管理场景的RAG Agent系统。"
                "项目最初的目标是让用户记录会议纪要、临时想法、工作计划和学习笔记。"
                "随后团队发现仅依靠向量检索无法满足真实场景需求。"
                "第四阶段开始补充 Query Router、Relation Expansion 和 Citation Rerank。"
                "第六阶段增加 Agentic Retrieval，让Agent自主决定是否继续搜索更多证据。"
                "第七阶段增加多模态能力，支持图片、音频以及视频内容检索。"
                "虽然已经完成约70%的核心功能，但仍存在 Summary质量不稳定、Parent Memory更新策略尚未成熟、Rerank模型成本较高等问题。"
                "未来系统会从简单向量数据库，演进为能理解用户长期行为并动态维护记忆结构的智能记忆系统。"
            ),
        )
        original_generate = llm_answer_service.generate_grounded_answer
        llm_answer_service.generate_grounded_answer = lambda **_: "这条记录主要讲：2026年3月到2026年5月期间，项目组推进个人知识管理场景的RAG Agent系统。"
        try:
            response = qa_service.answer_question(
                self.db,
                self.user_id,
                QARequest(
                    question="总结一下",
                    context_memory_id=str(memory.id),
                ),
            )
        finally:
            llm_answer_service.generate_grounded_answer = original_generate

        self.assertNotIn("为了避免只总结开头", response.answer)
        self.assertNotIn("完整总结如下", response.answer)
        self.assertNotRegex(response.answer, r"(?:^|\n)\s*1[.、]")
        self.assertIn("Summary质量不稳定", response.answer)
        self.assertIn("未来系统", response.answer)
        self.assertEqual(response.trace.metadata["context_strategy"], "full_summary")
        self.assertTrue(response.trace.metadata["context_strategy_debug"]["summary_repaired"])
        chunk_coverage = response.trace.metadata["context_strategy_debug"]["chunk_coverage_check"]
        self.assertTrue(chunk_coverage["passed"])

    def test_full_summary_rewrites_chunk_inventory_answer(self) -> None:
        content = (
            "附件：产品路线.md（text/markdown）\n\n"
            "一月调研阶段，团队集中访谈了早期用户，确认记录、检索和提醒是最核心的三个使用场景。"
            "二月设计阶段，团队完成了输入框、最近记录和 AI 侧栏的交互草图，并明确要减少分类负担。"
            "三月开发阶段，团队补齐了文档导入、切块、检索和引用展示，让文件也能进入问答链路。"
            "四月验证阶段，团队发现普通 topK 检索会漏掉长文后半部分，因此开始设计当前上下文策略。"
            "五月复盘阶段，团队重点处理全文总结、全文提取和选中文本问答，避免回答只覆盖开头。"
            "六月计划阶段，团队准备继续优化覆盖检查、证据引用和多模态文件阅读能力。"
        )
        memory = self._create_memory("产品路线", content, source_type="file")
        original_generate = llm_answer_service.generate_grounded_answer
        llm_answer_service.generate_grounded_answer = lambda **_: (
            "《产品路线》的完整总结如下，已按原文顺序覆盖全部 6 个片段：\n"
            "1. 附件：产品路线.md。\n"
            "2. 一月调研阶段，团队集中访谈了早期用户。"
        )
        try:
            response = qa_service.answer_question(
                self.db,
                self.user_id,
                QARequest(
                    question="总结一下这份文件",
                    active_doc_id=str(memory.id),
                    active_context_type="document",
                ),
            )
        finally:
            llm_answer_service.generate_grounded_answer = original_generate

        self.assertNotIn("完整总结如下", response.answer)
        self.assertNotRegex(response.answer, r"(?:^|\n)\s*1[.、]")
        self.assertNotIn("附件：", response.answer)
        self.assertIn("五月复盘", response.answer)
        self.assertEqual(response.trace.metadata["context_strategy_debug"]["summary_repair_reason"], "chunk_inventory")

    def test_full_summary_respects_char_limit_without_raw_supplement(self) -> None:
        content = (
            "附件：思想汇报20260501.docx（application/vnd.openxmlformats-officedocument.wordprocessingml.document）\n\n"
            "二月回到重庆家中与家人团聚，关注国家科技创新和低空经济发展。"
            "三月返校后投入无人机对抗横向课题，在真实项目实践中深化认识。"
            "四月参加组会和文献研读，围绕算法验证、数据整理和实验复现推进科研。"
            "五月总结阶段收获，反思作风、学习节奏和后续科研目标。"
        )
        memory = self._create_memory("思想汇报20260501", content, source_type="file")
        original_generate = llm_answer_service.generate_grounded_answer
        llm_answer_service.generate_grounded_answer = lambda **_: (
            "《思想汇报20260501》的完整总结如下，已按原文顺序覆盖全部片段："
            "1. 附件：思想汇报20260501.docx。"
            + content
        )
        try:
            response = qa_service.answer_question(
                self.db,
                self.user_id,
                QARequest(
                    question="总结不超过100字",
                    active_doc_id=str(memory.id),
                    active_context_type="document",
                ),
            )
        finally:
            llm_answer_service.generate_grounded_answer = original_generate

        self.assertLessEqual(len(response.answer), 100)
        self.assertNotIn("完整总结如下", response.answer)
        self.assertNotIn("为了避免只总结开头", response.answer)
        self.assertNotIn("附件：", response.answer)
        self.assertEqual(response.trace.metadata["context_strategy_debug"]["answer_char_limit"], 100)

    def test_active_context_identity_question_bypasses_document_route(self) -> None:
        memory = self._create_memory(
            "康老师组学生任务管理文档-2026年",
            "第4周完成阶段复盘，第5周开始推进新任务。",
            source_type="file",
        )

        route = query_router_service.route(
            "你是谁",
            "memory_only",
            {
                "active_doc_id": str(memory.id),
                "active_context_type": "document",
            },
        )
        self.assertEqual(route.route, "direct")
        self.assertFalse(route.should_retrieve)
        self.assertFalse(route.should_use_active_context)

        response = qa_service.answer_question(
            self.db,
            self.user_id,
            QARequest(
                question="你是谁",
                active_doc_id=str(memory.id),
                active_context_type="document",
            ),
        )

        self.assertIn("AI 助手", response.answer)
        self.assertNotIn("基于这条记录", response.answer)
        self.assertEqual(response.trace.metadata["query_route"], "direct")
        self.assertEqual(response.trace.answer_source, "direct_answer")

    def test_context_memory_weather_question_returns_tool_answer(self) -> None:
        memory = self._create_memory(
            "康老师组学生任务管理文档-2026年",
            "第4周完成阶段复盘，第5周开始推进新任务。",
            source_type="file",
        )

        route = query_router_service.route(
            "今天北京天气如何",
            "memory_only",
            {
                "context_memory_id": str(memory.id),
                "active_context_type": "record",
            },
        )
        self.assertEqual(route.route, "weather")
        self.assertFalse(route.should_use_active_context)

        response = qa_service.answer_question(
            self.db,
            self.user_id,
            QARequest(
                question="今天北京天气如何",
                context_memory_id=str(memory.id),
            ),
        )

        self.assertNotIn("康老师组学生任务管理文档", response.answer)
        self.assertIn("天气", response.answer)
        self.assertEqual(response.trace.metadata["query_route"], "weather")

    def test_document_summary_route_exposes_retrieval_scope(self) -> None:
        memory = self._create_memory(
            "项目周记",
            "第1周完成需求梳理。第2周完成原型。第3周开始开发。",
            source_type="file",
        )

        response = qa_service.answer_question(
            self.db,
            self.user_id,
            QARequest(
                question="这条记录讲了什么",
                active_doc_id=str(memory.id),
                active_context_type="document",
            ),
        )

        self.assertEqual(response.trace.metadata["query_route"], "document_op")
        self.assertEqual(response.trace.metadata["retrieval_scope"], "active_document")
        self.assertEqual(response.trace.metadata["answer_mode"], "summarize")

    def test_document_rewrite_weekly_report_uses_document_op(self) -> None:
        memory = self._create_memory(
            "研发推进记录",
            "本周完成需求澄清、接口联调和首页样式调整。下周计划补测试并处理线上反馈。",
            source_type="file",
        )

        response = qa_service.answer_question(
            self.db,
            self.user_id,
            QARequest(
                question="把这条记录改成周报",
                active_doc_id=str(memory.id),
                active_context_type="document",
            ),
        )

        self.assertEqual(response.trace.metadata["query_route"], "document_op")
        self.assertEqual(response.trace.metadata["answer_mode"], "transform")
        self.assertEqual(response.trace.metadata["retrieval_scope"], "active_document")
        self.assertIn("周报", response.answer)

    def test_ambiguous_context_query_asks_for_clarification(self) -> None:
        memory = self._create_memory(
            "会议记录",
            "这里记录了需求评审和上线安排。",
            source_type="file",
        )

        response = qa_service.answer_question(
            self.db,
            self.user_id,
            QARequest(
                question="这个怎么样",
                active_doc_id=str(memory.id),
                active_context_type="document",
            ),
        )

        self.assertEqual(response.trace.metadata["query_route"], "clarify")
        self.assertEqual(response.trace.metadata["answer_mode"], "clarify")
        self.assertIn("只看当前", response.answer)

    def test_llm_prompt_mode_for_summary(self) -> None:
        captured: dict[str, str] = {}
        original_chat_completion = llm_answer_service._chat_completion
        original_base_url = settings.openai_base_url
        original_api_key = settings.openai_api_key

        def fake_chat_completion(**kwargs):
            captured["system_prompt"] = kwargs["system_prompt"]
            captured["user_prompt"] = kwargs["user_prompt"]
            return "ok"

        settings.openai_base_url = "http://example.com"
        settings.openai_api_key = "test-key"
        llm_answer_service._chat_completion = fake_chat_completion
        try:
            result = llm_answer_service.generate_grounded_answer_result(
                question="总结一下",
                provider="local",
                model="none",
                context_blocks=["标题：测试\n内容：第一阶段完成需求。第二阶段开始开发。"],
                answer_mode="summarize",
            )
        finally:
            llm_answer_service._chat_completion = original_chat_completion
            settings.openai_base_url = original_base_url
            settings.openai_api_key = original_api_key

        self.assertEqual(result.answer, "ok")
        self.assertIn("当前任务是总结全文", captured["system_prompt"])
        self.assertIn("做完整总结", captured["user_prompt"])

    def test_llm_prompt_mode_for_transform(self) -> None:
        captured: dict[str, str] = {}
        original_chat_completion = llm_answer_service._chat_completion
        original_base_url = settings.openai_base_url
        original_api_key = settings.openai_api_key

        def fake_chat_completion(**kwargs):
            captured["system_prompt"] = kwargs["system_prompt"]
            captured["user_prompt"] = kwargs["user_prompt"]
            return "ok"

        settings.openai_base_url = "http://example.com"
        settings.openai_api_key = "test-key"
        llm_answer_service._chat_completion = fake_chat_completion
        try:
            result = llm_answer_service.generate_grounded_answer_result(
                question="改成周报",
                provider="local",
                model="none",
                context_blocks=["标题：测试\n内容：本周完成联调，下周补测试。"],
                answer_mode="transform",
            )
        finally:
            llm_answer_service._chat_completion = original_chat_completion
            settings.openai_base_url = original_base_url
            settings.openai_api_key = original_api_key

        self.assertEqual(result.answer, "ok")
        self.assertIn("当前任务是内容改写或格式转换", captured["system_prompt"])
        self.assertIn("只输出结果", captured["user_prompt"])


if __name__ == "__main__":
    unittest.main()
