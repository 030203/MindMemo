"""
记忆管理器 - 统一访问各层记忆的入口

核心职责：
1. 统一管理所有记忆层
2. 为Agent提供简洁的记忆访问接口
3. 处理跨层的记忆查询和更新

设计原则：
- 门面模式：隐藏记忆层的复杂性
- 依赖注入：通过构造函数传入db和user_id
- 按需加载：记忆层在第一次访问时初始化
"""
from uuid import UUID
from sqlalchemy.orm import Session
from typing import Optional

from .layers.working import WorkingMemory
from .layers.episodic import EpisodicMemory
from .layers.semantic import SemanticMemory
from .layers.goal import GoalMemory
from .layers.procedural import ProceduralMemory
from .layers.insight import InsightCache


class MemoryManager:
    """
    记忆管理器 - 所有Agent通过它访问Memory

    使用示例：
        mm = MemoryManager(db, user_id)

        # 访问工作记忆
        mm.working.add_turn("user", "今天天气怎么样")
        recent = mm.working.get_recent_turns(n=3)

        # 访问目标记忆
        goals = mm.goal.get_active_goals(limit=5)

        # 为Router提供上下文
        ctx = mm.get_context_for_router()
    """

    def __init__(self, db: Session, user_id: UUID):
        """
        初始化记忆管理器

        Args:
            db: 数据库会话
            user_id: 用户ID
        """
        self.db = db
        self.user_id = user_id

        # 各层记忆（延迟初始化）
        self._working: Optional[WorkingMemory] = None
        self._episodic: Optional[EpisodicMemory] = None
        self._semantic: Optional[SemanticMemory] = None
        self._goal: Optional[GoalMemory] = None
        self._procedural: Optional[ProceduralMemory] = None
        self._insights: Optional[InsightCache] = None

    @property
    def working(self) -> WorkingMemory:
        """获取工作记忆层"""
        if self._working is None:
            self._working = WorkingMemory()
        return self._working

    @property
    def episodic(self) -> EpisodicMemory:
        """获取情节记忆层"""
        if self._episodic is None:
            self._episodic = EpisodicMemory(self.db, self.user_id)
        return self._episodic

    @property
    def semantic(self) -> SemanticMemory:
        """获取语义记忆层"""
        if self._semantic is None:
            self._semantic = SemanticMemory(self.db, self.user_id)
        return self._semantic

    @property
    def goal(self) -> GoalMemory:
        """获取目标记忆层"""
        if self._goal is None:
            self._goal = GoalMemory(self.db, self.user_id)
        return self._goal

    @property
    def procedural(self) -> ProceduralMemory:
        """获取程序记忆层"""
        if self._procedural is None:
            self._procedural = ProceduralMemory(self.db, self.user_id)
        return self._procedural

    @property
    def insights(self) -> InsightCache:
        """获取洞察缓存层"""
        if self._insights is None:
            self._insights = InsightCache(self.db, self.user_id)
        return self._insights

    def get_context_for_router(self) -> dict:
        """
        为Router提供轻量上下文（用于快速路由决策）

        Returns:
            包含最近对话、活跃目标、待办任务的字典
        """
        return {
            "recent_conversation": self.working.get_recent_turns(n=3),
            "active_goals": self.goal.get_active_goals(limit=5),
            "pending_todos": self.procedural.get_pending_todos(limit=10),
        }

    def get_context_for_planner(self) -> dict:
        """
        为Planner提供完整上下文（用于任务规划）

        Returns:
            包含完整上下文信息的字典
        """
        return {
            **self.get_context_for_router(),
            "user_profile": self.semantic.get_user_profile(),
            "recent_insights": self.insights.get_recent(days=7),
        }

    def snapshot(self) -> dict:
        """
        导出完整快照（用于Agent详细上下文）

        Returns:
            包含所有记忆层摘要的字典
        """
        return {
            "working": self.working.to_dict(),
            "goals": self.goal.get_all(),
            "episodic_summary": self.episodic.get_summary(days=30),
            "semantic_summary": self.semantic.get_summary(),
        }
