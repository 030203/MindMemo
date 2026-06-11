from __future__ import annotations

import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models.evaluation import AgentRun, AgentRunStep  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.qa import QAContextMessage, QARequest  # noqa: E402
from app.services.bootstrap import DEMO_USER_EMAIL, initialize_database  # noqa: E402
from app.services.qa_service import qa_service  # noqa: E402


def main() -> None:
    initialize_database()
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == DEMO_USER_EMAIL)).scalar_one()
        response = qa_service.answer_question(
            db,
            user.id,
            QARequest(
                question="那具体有哪些步骤？",
                mode="memory_only",
                conversation_context=[
                    QAContextMessage(role="user", content="LangGraph 学习记录里提到了什么？"),
                    QAContextMessage(role="assistant", content="这条记录提到了 state graph、conditional edge 和 workflow。"),
                ],
            ),
        )
        if response.trace is None:
            raise SystemExit("phase11_agent_runs=failed: missing trace")
        execution_plan = response.trace.metadata.get("execution_plan")
        if not isinstance(execution_plan, dict):
            raise SystemExit("phase11_agent_runs=failed: missing execution_plan")
        if not execution_plan.get("subquestions") or not execution_plan.get("tools"):
            raise SystemExit("phase11_agent_runs=failed: incomplete execution_plan")
        first_subquestion = execution_plan.get("subquestions", [None])[0]
        if not isinstance(first_subquestion, dict):
            raise SystemExit("phase11_agent_runs=failed: structured subquestion missing")
        if not first_subquestion.get("question") or not first_subquestion.get("tool"):
            raise SystemExit("phase11_agent_runs=failed: structured subquestion incomplete")
        if execution_plan.get("planner_version") != "rule_based_v2":
            raise SystemExit("phase11_agent_runs=failed: planner_version not upgraded")
        if not isinstance(execution_plan.get("time_window"), dict):
            raise SystemExit("phase11_agent_runs=failed: time_window missing")
        if not isinstance(execution_plan.get("context_packing"), dict):
            raise SystemExit("phase11_agent_runs=failed: context_packing missing")
        agent_run_id = response.trace.metadata.get("agent_run_id")
        if not agent_run_id:
            raise SystemExit("phase11_agent_runs=failed: missing agent_run_id")
        run = db.execute(select(AgentRun).where(AgentRun.id == uuid.UUID(str(agent_run_id)))).scalar_one_or_none()
        if run is None:
            raise SystemExit("phase11_agent_runs=failed: run not persisted")
        steps = list(db.execute(select(AgentRunStep).where(AgentRunStep.run_id == run.id)).scalars().all())
        if len(steps) < 3:
            raise SystemExit("phase11_agent_runs=failed: not enough persisted steps")
        step_keys = {step.step_key for step in steps}
        if "query_route" not in step_keys or "chunk_retrieval" not in step_keys or "answer_generation" not in step_keys:
            raise SystemExit(f"phase11_agent_runs=failed: unexpected steps {sorted(step_keys)}")

        print(f"trace_id={response.trace.id}")
        print(f"agent_run_id={agent_run_id}")
        print(f"planner_version={execution_plan.get('planner_version')}")
        print(f"planned_subquestions={len(execution_plan.get('subquestions', []))}")
        print(f"step_count={len(steps)}")
        print("phase11_agent_runs=passed")


if __name__ == "__main__":
    main()
