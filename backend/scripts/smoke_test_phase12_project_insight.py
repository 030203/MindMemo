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
from app.services.dashboard_service import dashboard_service  # noqa: E402
from app.services.qa_service import qa_service  # noqa: E402


def main() -> None:
    initialize_database()
    with SessionLocal() as db:
        user = db.execute(select(User).where(User.email == DEMO_USER_EMAIL)).scalar_one()
        insights = dashboard_service.get_insights(db, user.id).cards
        project_card = next((card for card in insights if card.kind == "project"), None)
        if project_card is None:
            raise SystemExit("phase12_project_insight=failed: missing project card")
        if "未完成任务" not in project_card.detail and "任务" not in project_card.detail:
            raise SystemExit("phase12_project_insight=failed: project detail missing task linkage")

        response = qa_service.answer_question(
            db,
            user.id,
            QARequest(
                question="最近项目进展怎么样？",
                mode="memory_only",
            ),
        )
        if response.trace is None:
            raise SystemExit("phase12_project_insight=failed: missing trace")
        if response.trace.answer_source != "insight_agent":
            raise SystemExit(f"phase12_project_insight=failed: unexpected answer_source {response.trace.answer_source}")
        if "项目" not in response.answer and "project" not in response.answer.lower():
            raise SystemExit("phase12_project_insight=failed: project answer missing project context")
        if "下一步" not in response.answer and "风险" not in response.answer and "阻塞" not in response.answer:
            raise SystemExit("phase12_project_insight=failed: project answer missing action/risk signal")

        print(f"project_card_value={project_card.value}")
        print(f"trace_id={response.trace.id}")
        print("phase12_project_insight=passed")


if __name__ == "__main__":
    main()
