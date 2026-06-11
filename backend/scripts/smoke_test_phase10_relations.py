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


def create_memory(base_url: str, token: str, title: str, content: str, category: str = "learning") -> dict:
    return request_json(
        f"{base_url}/memories",
        method="POST",
        payload={
            "title": title,
            "content": content,
            "category": category,
            "source_type": "memo",
            "run_ai_parse": True,
        },
        token=token,
    )["data"]


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

    first = create_memory(
        args.base_url,
        token,
        "Phase 10 relation seed A",
        "\u6211\u6700\u8fd1\u5728\u7814\u7a76 RAG \u67b6\u6784\u548c Agent Workflow\u3002",
    )
    second = create_memory(
        args.base_url,
        token,
        "Phase 10 relation seed B",
        "\u4eca\u5929\u7ee7\u7eed\u7814\u7a76 RAG \u68c0\u7d22\u8bc4\u4f30\u3001Agent Workflow trace \u548c\u957f\u671f\u8bb0\u5fc6\u3002",
    )
    print("memories=ok")

    related = request_json(f"{args.base_url}/memories/{first['id']}/related", token=token)["data"]
    print(f"related_count={len(related)}")
    if not related:
        raise RuntimeError("expected related memories")

    matching = [item for item in related if item["id"] == second["id"]]
    if not matching:
        raise RuntimeError(f"missing expected related memory {second['id']}: {related}")
    if matching[0]["score"] <= 0:
        raise RuntimeError(f"related memory score should be positive: {matching[0]}")

    rebuilt = request_json(
        f"{args.base_url}/memories/{first['id']}/relations/rebuild",
        method="POST",
        token=token,
    )["data"]
    if not any(item["id"] == second["id"] for item in rebuilt):
        raise RuntimeError("rebuilt relations should include the related seed memory")

    print(f"relation_type={matching[0]['relation_type']}")
    print(f"relation_score={matching[0]['score']}")
    print("status=ok")


if __name__ == "__main__":
    main()
