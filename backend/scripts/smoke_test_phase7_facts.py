from __future__ import annotations

import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def post_json(url: str, payload: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str, token: str) -> dict:
    request = urllib.request.Request(url=url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    base_url = "http://127.0.0.1:8000/api/v1"
    login = post_json(
        f"{base_url}/auth/login",
        {"account": "demo@example.com", "password": "demo123456"},
    )
    token = login["data"]["access_token"]
    print("auth=ok")

    cases = [
        ("expense", "今天花了100元买耳机"),
        ("mood", "昨天晚上睡得不好，今天有点疲惫"),
        ("learning", "我最近在研究RAG架构和 Agent Workflow"),
        ("plan", "下个月记得交房租"),
    ]

    for expected_type, content in cases:
        created = post_json(
            f"{base_url}/memories",
            {
                "title": f"Phase 7 fact test {expected_type}",
                "content": content,
                "category": "memo",
                "source_type": "memo",
                "run_ai_parse": True,
            },
            token=token,
        )["data"]
        detail = get_json(f"{base_url}/memories/{created['id']}", token=token)["data"]
        fact_types = [fact["fact_type"] for fact in detail["extracted_facts"]]
        print(f"{expected_type}_facts={fact_types}")
        if expected_type not in fact_types:
            raise RuntimeError(f"missing expected fact type {expected_type}: {fact_types}")

    print("status=ok")


if __name__ == "__main__":
    main()
