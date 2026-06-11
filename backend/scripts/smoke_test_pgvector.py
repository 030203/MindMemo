from pathlib import Path
import json
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


def main() -> None:
    login = post_json(
        "http://127.0.0.1:8000/api/v1/auth/login",
        {"account": "demo@example.com", "password": "demo123456"},
    )
    token = login["data"]["access_token"]

    post_json(
        "http://127.0.0.1:8000/api/v1/memories",
        {
            "title": "pgvector 本地验收记录",
            "content": "这是一条用于 PostgreSQL 和 pgvector 本地验收的记录，包含向量检索、embedding 持久化和 SQL 召回。",
            "category": "learning",
            "source_type": "memo",
            "run_ai_parse": True,
        },
        token=token,
    )

    qa = post_json(
        "http://127.0.0.1:8000/api/v1/qa/ask",
        {"question": "我之前记录过哪些和 pgvector 或向量检索有关的内容？", "mode": "memory_only"},
        token=token,
    )

    print(qa["data"]["answer"])
    print("TOP_CITATION:", qa["data"]["citations"][0]["title"])


if __name__ == "__main__":
    main()
