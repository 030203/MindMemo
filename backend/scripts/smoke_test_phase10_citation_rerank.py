from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
import uuid


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


def create_memory(base_url: str, token: str, title: str, content: str) -> dict:
    return request_json(
        f"{base_url}/memories",
        method="POST",
        payload={
            "title": title,
            "content": content,
            "category": "learning",
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

    run_id = uuid.uuid4().hex[:8]
    anchor_title = f"Phase 10 rerank anchor {run_id}"
    related_title = f"Phase 10 rerank related {run_id}"
    create_memory(
        args.base_url,
        token,
        anchor_title,
        f"{anchor_title} \u8bb0\u5f55 RAG citation rerank\u3001direct chunk \u547d\u4e2d\u548c Memory Graph \u4e0a\u4e0b\u6587\u3002",
    )
    create_memory(
        args.base_url,
        token,
        related_title,
        f"{related_title} \u8bb0\u5f55 RAG citation rerank\u3001relation score \u548c Memory Graph \u6269\u5c55\u3002",
    )
    print("memories=ok")

    question = f"\u8bf7\u56de\u5fc6 {anchor_title} \u7684\u4e0a\u4e0b\u6587\u7ebf\u7d22"
    answer = request_json(
        f"{args.base_url}/qa/ask",
        method="POST",
        payload={"question": question, "mode": "memory_only"},
        token=token,
    )["data"]
    if not answer["citations"]:
        raise RuntimeError("expected citations")
    if answer["citations"][0]["title"] != anchor_title:
        raise RuntimeError(f"direct citation should rank first: {answer['citations']}")
    if not all(0 <= float(citation["score"]) <= 1.1 for citation in answer["citations"]):
        raise RuntimeError(f"reranked citation scores should be normalized: {answer['citations']}")
    print("qa=ok")

    trace_url = f"{args.base_url}/qa/traces?{urllib.parse.urlencode({'limit': 8})}"
    traces = request_json(trace_url, token=token)["data"]
    matching = [trace for trace in traces if trace["question"] == question]
    if not matching:
        raise RuntimeError("missing trace for reranked QA")
    latest = matching[0]
    if latest["metadata"].get("citation_rerank_strategy") != "citation_rerank_v1":
        raise RuntimeError(f"missing rerank metadata: {latest}")

    print(f"top_citation={answer['citations'][0]['title']}")
    print(f"rerank_strategy={latest['metadata']['citation_rerank_strategy']}")
    print("status=ok")


if __name__ == "__main__":
    main()
