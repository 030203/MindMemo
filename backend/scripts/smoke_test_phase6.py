from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def request_json(
    method: str,
    url: str,
    payload: dict | None = None,
    token: str | None = None,
) -> dict:
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url=url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {body}") from exc


def get_json(url: str, token: str | None = None) -> dict:
    return request_json("GET", url, token=token)


def post_json(url: str, payload: dict, token: str | None = None) -> dict:
    return request_json("POST", url, payload=payload, token=token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 6 demo smoke test for MySecondBrain.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--account", default="demo@example.com")
    parser.add_argument("--password", default="demo123456")
    parser.add_argument(
        "--send-notification",
        choices=["pushdeer", "serverchan", "wecom"],
        help="Optionally send one real test notification through the selected channel.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    login = post_json(
        f"{base_url}/auth/login",
        {"account": args.account, "password": args.password},
    )
    token = login["data"]["access_token"]
    print("auth=ok")

    settings = get_json(f"{base_url}/settings", token=token)["data"]
    providers = get_json(f"{base_url}/settings/notification-providers", token=token)["data"]
    configured = [item["channel"] for item in providers if item["configured"]]
    print(f"notify_channels={settings['notify_channels']}")
    print(f"configured_providers={configured}")

    if args.send_notification:
        result = post_json(
            f"{base_url}/settings/notifications/test",
            {"channel": args.send_notification},
            token=token,
        )["data"]
        print(f"notification_test={result['channel']}:{result['sent']}")

    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    title = f"Phase 6 smoke project memory {suffix}"
    post_json(
        f"{base_url}/memories",
        {
            "title": title,
            "content": "This memory is created by the Phase 6 smoke test to verify review queue and todo conversion.",
            "category": "project",
            "source_type": "memo",
            "run_ai_parse": True,
        },
        token=token,
    )
    print("memory_create=ok")

    reviews = get_json(f"{base_url}/review-queue", token=token)["data"]
    target_review = next(
        (
            item
            for item in reviews
            if item["target_title"] == title and item["status"] == "pending"
        ),
        None,
    )
    if target_review is None:
        raise RuntimeError("review_queue=missing generated pending item")
    print(f"review_queue=ok:{target_review['review_type']}")

    post_json(
        f"{base_url}/review-queue/{target_review['id']}/convert-to-todo",
        {"note": "Converted by Phase 6 smoke test."},
        token=token,
    )
    print("review_convert_to_todo=ok")

    query = urllib.parse.urlencode({"q": title})
    todos = get_json(f"{base_url}/todos?{query}", token=token)["data"]
    if not any(item["title"] == title for item in todos):
        raise RuntimeError("todo=missing converted todo")
    print("todo_conversion=ok")
    print("status=ok")


if __name__ == "__main__":
    main()
