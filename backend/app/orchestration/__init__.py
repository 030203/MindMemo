"""
Orchestration模块 - 工作流编排

包含：
- Router: 意图路由器 (fast/slow 分流)
- QAWorkflow: 问答流程编排
- InsightWorkflow: 洞察流程编排
"""

from .router import Router, RouterResult
from .qa_workflow import QAWorkflow, qa_workflow

__all__ = ["Router", "RouterResult", "QAWorkflow", "qa_workflow"]
