from __future__ import annotations

import argparse
import json
import urllib.request


def request_json(url: str, method: str = "GET", payload: dict | None = None, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def seed_memory(base_url: str, token: str, title: str, content: str) -> None:
    request_json(
        f"{base_url}/memories",
        method="POST",
        payload={
            "title": title,
            "content": content,
            "category": "memo",
            "source_type": "memo",
            "run_ai_parse": True,
        },
        token=token,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    args = parser.parse_args()

    login = request_json(
        f"{args.base_url}/auth/login",
        method="POST",
        payload={"account": "demo@example.com", "password": "demo123456"},
    )
    token = login["data"]["access_token"]
    print("auth=ok")

    seed_memory(args.base_url, token, "Phase 7 dashboard expense", "\u4eca\u5929\u82b1\u4e8642\u5143\u4e70\u5496\u5561")
    seed_memory(args.base_url, token, "Phase 7 dashboard mood", "\u6628\u5929\u7761\u5f97\u4e0d\u597d\uff0c\u4eca\u5929\u6709\u70b9\u75b2\u60eb")
    seed_memory(args.base_url, token, "Phase 7 dashboard learning", "\u6211\u6700\u8fd1\u5728\u7814\u7a76RAG\u67b6\u6784\u548c Agent Workflow")
    seed_memory(args.base_url, token, "Phase 7 dashboard plan", "\u4e0b\u4e2a\u6708\u8bb0\u5f97\u4ea4\u623f\u79df")
    print("seed=ok")

    insights = request_json(f"{args.base_url}/dashboard/insights", token=token)["data"]
    cards = insights["cards"]
    kinds = {card["kind"] for card in cards}
    expected = {"expense", "mood", "learning", "plan"}
    if kinds != expected:
        raise RuntimeError(f"unexpected insight kinds: {kinds}")
    for card in cards:
        if not card["title"] or not card["value"] or not card["question"]:
            raise RuntimeError(f"incomplete card: {card}")
    print(f"insight_cards={sorted(kinds)}")
    print("status=ok")


if __name__ == "__main__":
    main()
