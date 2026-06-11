from __future__ import annotations

import argparse
import json
import uuid
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


def create_memory(base_url: str, token: str, title: str, content: str) -> dict:
    return request_json(
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
    alpha_title = f"Phase 10 relation QA alpha {run_id}"
    beta_title = f"Phase 10 relation QA beta {run_id}"
    first = create_memory(
        args.base_url,
        token,
        alpha_title,
        f"\u8fd9\u662f {alpha_title}\uff0c\u8bb0\u5f55\u4e86\u4e2a\u4eba\u77e5\u8bc6\u5e93\u7684\u68c0\u7d22\u4e0a\u4e0b\u6587\u95ee\u9898\u3002",
    )
    second = create_memory(
        args.base_url,
        token,
        beta_title,
        f"\u8fd9\u662f {beta_title}\uff0c\u8865\u5145\u4e86\u4e2a\u4eba\u77e5\u8bc6\u5e93\u3001\u68c0\u7d22\u4e0a\u4e0b\u6587\u548c\u8bb0\u5fc6\u5173\u7cfb\u3002",
    )
    print("memories=ok")

    question = f"{alpha_title} \u7684\u4e0a\u4e0b\u6587\u6709\u54ea\u4e9b\uff1f"
    answer = request_json(
        f"{args.base_url}/qa/ask",
        method="POST",
        payload={"question": question, "mode": "memory_only"},
        token=token,
    )["data"]
    if not answer["answer"]:
        raise RuntimeError("qa answer should not be empty")
    if len(answer["citations"]) < 4:
        raise RuntimeError(f"expected relation-expanded citations: {answer['citations']}")
    print("qa=ok")

    trace_url = f"{args.base_url}/qa/traces?{urllib.parse.urlencode({'limit': 5})}"
    traces = request_json(trace_url, token=token)["data"]
    matching = [trace for trace in traces if trace["question"] == question]
    if not matching:
        raise RuntimeError("missing trace for relation-expanded QA")
    latest = matching[0]
    if latest["retrieval_strategy"] != "chunk_v1+relation_expand_v1":
        raise RuntimeError(f"unexpected retrieval strategy: {latest['retrieval_strategy']}")
    if latest["metadata"].get("related_memory_count", 0) <= 0:
        raise RuntimeError(f"trace missing related memory expansion: {latest}")
    if not latest["candidates"]:
        raise RuntimeError(f"trace missing retrieval candidates: {latest}")
    first_candidate = latest["candidates"][0]
    for field in ["entered_direct_window", "entered_rerank", "final_selected"]:
        if field not in first_candidate:
            raise RuntimeError(f"trace candidate missing field {field}: {first_candidate}")
    print(f"strategy={latest['retrieval_strategy']}")
    print(f"related_memory_count={latest['metadata']['related_memory_count']}")
    print(
        "candidate_flags="
        f"{first_candidate['entered_direct_window']}/"
        f"{first_candidate['entered_rerank']}/"
        f"{first_candidate['final_selected']}"
    )
    print("status=ok")


if __name__ == "__main__":
    main()
