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
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--skip-live", action="store_true")
    args = parser.parse_args()

    login = request_json(
        f"{args.base_url}/auth/login",
        method="POST",
        payload={"account": "demo@example.com", "password": "demo123456"},
    )
    token = login["data"]["access_token"]
    print("auth=ok")

    if args.skip_live:
        print("live_external_calls=skipped")
        print("status=ok")
        return

    weather = request_json(
        f"{args.base_url}/tools/weather",
        method="POST",
        payload={"location": "Beijing"},
        token=token,
    )["data"]
    if not weather["configured"] or not weather["description"]:
        raise RuntimeError(f"weather tool not ready: {weather}")
    weather_live_ok = not str(weather["description"]).startswith("OpenWeather request failed:")
    print(f"weather={'ok' if weather_live_ok else 'unavailable'}:{weather['location']}:{weather['description']}")

    search = request_json(
        f"{args.base_url}/tools/web-search",
        method="POST",
        payload={"query": "Tavily search API official docs", "max_results": 3},
        token=token,
    )["data"]
    if not search["configured"] or not search["results"]:
        raise RuntimeError(f"web search tool not ready: {search}")
    print(f"web_search=ok:{len(search['results'])}")

    if weather_live_ok:
        qa_weather = request_json(
            f"{args.base_url}/qa/ask",
            method="POST",
            payload={"question": "\u5317\u4eac\u5929\u6c14\u600e\u4e48\u6837\uff1f", "mode": "hybrid_web"},
            token=token,
        )["data"]
        if not any(citation["type"] == "weather" for citation in qa_weather["citations"]):
            raise RuntimeError(f"hybrid weather QA missing weather citation: {qa_weather}")
        print("hybrid_weather_qa=ok")
    else:
        print("hybrid_weather_qa=skipped")

    qa_web = request_json(
        f"{args.base_url}/qa/ask",
        method="POST",
        payload={"question": "\u8054\u7f51\u67e5\u4e00\u4e0b Tavily \u662f\u4ec0\u4e48\uff1f", "mode": "hybrid_web"},
        token=token,
    )["data"]
    if not any(citation["type"] == "web" for citation in qa_web["citations"]):
        raise RuntimeError(f"hybrid web QA missing web citation: {qa_web}")
    print("hybrid_web_qa=ok")

    qa_fact = request_json(
        f"{args.base_url}/qa/ask",
        method="POST",
        payload={"question": "\u6211\u8fd9\u4e2a\u6708\u603b\u5171\u82b1\u4e86\u591a\u5c11\u94b1\uff1f", "mode": "hybrid_web"},
        token=token,
    )["data"]
    if any(citation["type"] == "web" for citation in qa_fact["citations"]):
        raise RuntimeError(f"hybrid fact QA should not route to web: {qa_fact}")
    print("hybrid_fact_route=ok")
    print("status=ok")


if __name__ == "__main__":
    main()
