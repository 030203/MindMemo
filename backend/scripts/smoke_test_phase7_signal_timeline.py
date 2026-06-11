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


def list_signals(base_url: str, token: str, fact_type: str | None = None) -> list[dict]:
    path = f"{base_url}/timeline/signals"
    if fact_type:
        path = f"{path}?{urllib.parse.urlencode({'fact_type': fact_type})}"
    return request_json(path, token=token)["data"]


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

    seed_memory(args.base_url, token, "Phase 7 signal expense", "\u4eca\u5929\u82b1\u4e8658\u5143\u4e70\u4e66")
    seed_memory(args.base_url, token, "Phase 7 signal mood", "\u4eca\u5929\u7761\u5f97\u4e0d\u597d\uff0c\u6709\u4e00\u70b9\u7126\u8651")
    seed_memory(args.base_url, token, "Phase 7 signal learning", "\u6211\u6700\u8fd1\u5728\u7814\u7a76 LangGraph \u548c RAG \u67b6\u6784")
    seed_memory(args.base_url, token, "Phase 7 signal plan", "\u660e\u5929\u8bb0\u5f97\u6574\u7406\u9879\u76ee\u8def\u7ebf\u56fe")
    print("seed=ok")

    signals = list_signals(args.base_url, token)
    kinds = {signal["fact_type"] for signal in signals}
    expected = {"expense", "mood", "learning", "plan"}
    missing = expected - kinds
    if missing:
        raise RuntimeError(f"missing signal types: {missing}")

    learning_signals = list_signals(args.base_url, token, "learning")
    if not learning_signals or any(signal["fact_type"] != "learning" for signal in learning_signals):
        raise RuntimeError(f"learning filter failed: {learning_signals}")

    required_fields = {"id", "memory_id", "fact_type", "title", "summary", "event_time", "confidence_score", "tone"}
    for signal in signals[:4]:
        missing_fields = required_fields - set(signal)
        if missing_fields:
            raise RuntimeError(f"signal missing fields {missing_fields}: {signal}")

    print(f"signal_types={sorted(kinds)}")
    print("learning_filter=ok")
    print("status=ok")


if __name__ == "__main__":
    main()
