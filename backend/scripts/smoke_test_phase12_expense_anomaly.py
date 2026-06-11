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
        expense_card = next((card for card in insights if card.kind == "expense"), None)
        if expense_card is None:
            raise SystemExit("phase12_expense_anomaly=failed: missing expense card")

        response = qa_service.answer_question(
            db,
            user.id,
            QARequest(
                question="帮我分析一下本月消费概况",
                mode="memory_only",
            ),
        )
        if response.trace is None:
            raise SystemExit("phase12_expense_anomaly=failed: missing trace")
        if response.trace.answer_source not in {"insight_agent", "fact_insight"}:
            raise SystemExit(f"phase12_expense_anomaly=failed: unexpected answer_source {response.trace.answer_source}")
        if "消费" not in response.answer:
            raise SystemExit("phase12_expense_anomaly=failed: answer missing expense context")
        if "异常提示" not in " ".join(expense_card.items) and "异常提示" not in response.answer:
            raise SystemExit("phase12_expense_anomaly=failed: anomaly hint missing")

        print(f"expense_card_value={expense_card.value}")
        print(f"answer_source={response.trace.answer_source}")
        print(f"trace_id={response.trace.id}")
        print("phase12_expense_anomaly=passed")


if __name__ == "__main__":
    main()
