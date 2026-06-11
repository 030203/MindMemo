from __future__ import annotations

import argparse
import json
import uuid
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
    first = create_memory(
        args.base_url,
        token,
        f"Phase 10 understanding RAG {run_id}",
        f"\u4eca\u5929\u7814\u7a76 RAG\u3001hybrid retrieval\u3001rerank \u548c Memory Graph\uff0c\u8fd9\u662f {run_id}\u3002",
    )
    second = create_memory(
        args.base_url,
        token,
        f"Phase 10 understanding Agent {run_id}",
        f"\u7ee7\u7eed\u8bbe\u8ba1 Agent Workflow\u3001tool calling\u3001trace \u548c Memory Graph\uff0c\u8fd9\u662f {run_id}\u3002",
    )
    print("memories=ok")

    detail = request_json(f"{args.base_url}/memories/{first['id']}", token=token)["data"]
    expected_terms = {"RAG", "Memory Graph"}
    seen_terms = set(detail["keywords"]) | set(detail["entities"]) | set(detail["tags"])
    if not expected_terms <= seen_terms:
        raise RuntimeError(f"missing understanding terms {expected_terms - seen_terms}: {detail}")
    learning_facts = [fact for fact in detail["extracted_facts"] if fact["fact_type"] == "learning"]
    if not learning_facts:
        raise RuntimeError(f"missing learning fact: {detail['extracted_facts']}")
    fact_topics = set(learning_facts[0]["structured_payload"].get("topics", []))
    if "Memory Graph" not in fact_topics:
        raise RuntimeError(f"learning fact missing Memory Graph topic: {learning_facts}")

    related = request_json(f"{args.base_url}/memories/{first['id']}/related", token=token)["data"]
    matching = [item for item in related if item["id"] == second["id"]]
    if not matching:
        raise RuntimeError(f"missing related memory: {related}")
    if matching[0]["relation_type"] not in {"shared_entity", "shared_fact", "shared_semantic_signal"}:
        raise RuntimeError(f"unexpected relation type: {matching[0]}")

    print(f"keywords={detail['keywords'][:5]}")
    print(f"entities={detail['entities'][:5]}")
    print(f"relation_type={matching[0]['relation_type']}")
    print("status=ok")


if __name__ == "__main__":
    main()
