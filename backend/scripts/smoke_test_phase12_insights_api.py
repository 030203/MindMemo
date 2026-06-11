from __future__ import annotations

import os
from pathlib import Path
import sys

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402
from app.services.bootstrap import DEMO_USER_EMAIL, initialize_database  # noqa: E402
from app.services.dashboard_service import dashboard_service  # noqa: E402


def _assert_ok(response, label: str) -> dict:
    if response.status_code != 200:
        raise SystemExit(f"{label}=failed: unexpected status {response.status_code}")
    payload = response.json()
    if payload.get("code") != 0:
        raise SystemExit(f"{label}=failed: api code {payload.get('code')}")
    return payload.get("data") or {}


def main() -> None:
    initialize_database()
    dashboard_service.invalidate_insight_cache()
    with TestClient(app) as client:
        login_response = client.post(
            "/api/v1/auth/login",
            json={
                "account": DEMO_USER_EMAIL,
                "password": "demo123456",
            },
        )
        login_payload = _assert_ok(login_response, "phase12_insights_api")
        access_token = login_payload.get("access_token")
        if not access_token:
            raise SystemExit("phase12_insights_api=failed: missing access token")
        headers = {"Authorization": f"Bearer {access_token}"}

        overview = _assert_ok(client.get("/api/v1/insights/overview", headers=headers), "phase12_insights_api")
        cards = overview.get("cards") or []
        if len(cards) < 3:
            raise SystemExit("phase12_insights_api=failed: overview cards missing")
        cache_after_first = dashboard_service.cache_stats()

        _assert_ok(client.get("/api/v1/insights/overview", headers=headers), "phase12_insights_api_cache")
        cache_after_second = dashboard_service.cache_stats()
        if cache_after_second.get("hits", 0) <= cache_after_first.get("hits", 0):
            raise SystemExit("phase12_insights_api=failed: repeated overview did not hit insight cache")

        expense_payload = _assert_ok(client.get("/api/v1/insights/expenses", headers=headers), "phase12_insights_api")
        expense_cards = expense_payload.get("cards") or []
        if len(expense_cards) != 1 or expense_cards[0].get("kind") != "expense":
            raise SystemExit("phase12_insights_api=failed: expense route mismatch")
        if "sources" not in expense_cards[0]:
            raise SystemExit("phase12_insights_api=failed: expense sources missing")

        reflection_payload = _assert_ok(client.get("/api/v1/insights/reflection", headers=headers), "phase12_insights_api")
        reflection_cards = reflection_payload.get("cards") or []
        reflection_kinds = {card.get("kind") for card in reflection_cards}
        if "mood" not in reflection_kinds and "learning" not in reflection_kinds:
            raise SystemExit("phase12_insights_api=failed: reflection route missing expected cards")

        window_payload = _assert_ok(
            client.get("/api/v1/insights/overview?window=7d", headers=headers),
            "phase12_insights_api_window",
        )
        window_cards = window_payload.get("cards") or []
        if len(window_cards) < 3:
            raise SystemExit("phase12_insights_api=failed: time window cards missing")

        invalid_window_response = client.get("/api/v1/insights/overview?window=invalid", headers=headers)
        if invalid_window_response.status_code != 422:
            raise SystemExit("phase12_insights_api=failed: invalid time window was accepted")

        expense_detail = _assert_ok(
            client.get("/api/v1/insights/expense?window=7d", headers=headers),
            "phase12_insight_detail",
        )
        if expense_detail.get("kind") != "expense":
            raise SystemExit("phase12_insights_api=failed: expense detail route mismatch")

        invalid_kind_response = client.get("/api/v1/insights/not-a-kind", headers=headers)
        if invalid_kind_response.status_code != 422:
            raise SystemExit("phase12_insights_api=failed: invalid insight kind was accepted")

        source_count = sum(len(card.get("sources") or []) for card in cards)
        if source_count <= 0:
            raise SystemExit("phase12_insights_api=failed: no insight sources returned")

        print(f"overview_cards={len(cards)}")
        print(f"window_cards={len(window_cards)}")
        print(f"expense_detail_kind={expense_detail.get('kind')}")
        print(f"reflection_kinds={sorted(reflection_kinds)}")
        print(f"source_count={source_count}")
        print(f"insight_cache_hits={cache_after_second.get('hits')}")
        print("phase12_insights_api=passed")


if __name__ == "__main__":
    main()
