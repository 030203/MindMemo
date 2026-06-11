from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.qa import QARequest  # noqa: E402
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
                question="帮我总结一下最近主要在研究哪些技术",
                mode="memory_only",
            ),
        )
        if response.trace is None:
            raise SystemExit("phase12_insight_agent=failed: missing trace")
        if response.trace.answer_source != "insight_agent":
            raise SystemExit(f"phase12_insight_agent=failed: unexpected answer_source {response.trace.answer_source}")
        execution_plan = response.trace.metadata.get("execution_plan")
        if not isinstance(execution_plan, dict) or execution_plan.get("route") != "insight":
            raise SystemExit("phase12_insight_agent=failed: insight plan missing")
        if not response.answer.strip():
            raise SystemExit("phase12_insight_agent=failed: empty answer")
        print(f"trace_id={response.trace.id}")
        print(f"answer_source={response.trace.answer_source}")
        print(f"planner_version={execution_plan.get('planner_version')}")
        print("phase12_insight_agent=passed")


if __name__ == "__main__":
    main()
