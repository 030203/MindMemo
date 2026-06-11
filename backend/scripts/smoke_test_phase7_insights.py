from __future__ import annotations

import argparse
import json
import urllib.request


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


def seed_memory(base_url: str, token: str, title: str, content: str) -> None:
    post_json(
        f"{base_url}/memories",
        {
            "title": title,
            "content": content,
            "category": "memo",
            "source_type": "memo",
            "run_ai_parse": True,
        },
        token=token,
    )


def ask(base_url: str, token: str, question: str) -> dict:
    return post_json(
        f"{base_url}/qa/ask",
        {"question": question, "mode": "memory_only"},
        token=token,
    )["data"]


def assert_contains(name: str, text: str, expected_tokens: list[str]) -> None:
    missing = [token for token in expected_tokens if token not in text]
    if missing:
        raise RuntimeError(f"{name} answer missing {missing}: {text}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    args = parser.parse_args()

    login = post_json(
        f"{args.base_url}/auth/login",
        {"account": "demo@example.com", "password": "demo123456"},
    )
    token = login["data"]["access_token"]
    print("auth=ok")

    seed_memory(args.base_url, token, "Phase 7 insight expense 1", "\u4eca\u5929\u82b1\u4e86100\u5143\u4e70\u8033\u673a")
    seed_memory(args.base_url, token, "Phase 7 insight expense 2", "\u4eca\u5929\u82b1\u4e8630\u5143\u4e70\u5496\u5561")
    seed_memory(args.base_url, token, "Phase 7 insight mood", "\u6628\u5929\u665a\u4e0a\u7761\u5f97\u4e0d\u597d\uff0c\u4eca\u5929\u6709\u70b9\u75b2\u60eb")
    seed_memory(args.base_url, token, "Phase 7 insight learning", "\u6211\u6700\u8fd1\u5728\u7814\u7a76RAG\u67b6\u6784\u548c Agent Workflow")
    print("seed=ok")

    expense = ask(args.base_url, token, "\u6211\u8fd9\u4e2a\u6708\u603b\u5171\u82b1\u4e86\u591a\u5c11\u94b1\uff1f")
    assert_contains("expense", expense["answer"], ["CNY", "\u652f\u51fa"])
    if not expense["citations"]:
        raise RuntimeError("expense answer should include citations")
    print("expense_insight=ok")

    mood = ask(args.base_url, token, "\u6211\u6700\u8fd1\u60c5\u7eea\u600e\u4e48\u6837\uff1f")
    assert_contains("mood", mood["answer"], ["\u60c5\u7eea", "\u72b6\u6001"])
    print("mood_insight=ok")

    learning = ask(args.base_url, token, "\u6211\u6700\u8fd1\u5728\u7814\u7a76\u54ea\u4e9b\u6280\u672f\uff1f")
    assert_contains("learning", learning["answer"], ["RAG", "Agent"])
    print("learning_insight=ok")

    print("status=ok")


if __name__ == "__main__":
    main()
