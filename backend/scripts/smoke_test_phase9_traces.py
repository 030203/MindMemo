from __future__ import annotations

import argparse
import json
import urllib.parse
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

    question = "\u6211\u6700\u8fd1\u5173\u4e8e RAG \u67b6\u6784\u8bb0\u5f55\u4e86\u4ec0\u4e48\uff1f"
    answer = request_json(
        f"{args.base_url}/qa/ask",
        method="POST",
        payload={"question": question, "mode": "memory_only"},
        token=token,
    )["data"]
    if not answer["answer"]:
        raise RuntimeError("qa answer should not be empty")
    print("qa=ok")

    trace_url = f"{args.base_url}/qa/traces?{urllib.parse.urlencode({'limit': 5})}"
    traces = request_json(trace_url, token=token)["data"]
    matching = [trace for trace in traces if trace["question"] == question]
    if not matching:
        raise RuntimeError(f"missing retrieval trace for question: {question}")

    latest = matching[0]
    required_fields = {"id", "question", "mode", "retrieval_strategy", "answer_source", "candidates", "selected_citations", "metadata", "created_at"}
    missing = required_fields - set(latest)
    if missing:
        raise RuntimeError(f"trace missing fields: {missing}")
    if latest["metadata"].get("citation_count") is None:
        raise RuntimeError(f"trace metadata missing citation_count: {latest}")
    if not latest["metadata"].get("query_route"):
        raise RuntimeError(f"trace metadata missing query_route: {latest}")

    print(f"trace_source={latest['answer_source']}")
    print(f"trace_route={latest['metadata']['query_route']}")
    print(f"trace_candidates={len(latest['candidates'])}")
    print("status=ok")


if __name__ == "__main__":
    main()
