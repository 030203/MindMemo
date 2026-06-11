from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.core.config import settings
from app.schemas.external_tools import WebSearchResponse, WebSearchResult


class WebSearchService:
    def is_configured(self) -> bool:
        return bool(settings.tavily_api_key)

    def search(self, query: str, max_results: int = 5) -> WebSearchResponse:
        normalized_query = query.strip()
        if not normalized_query:
            return WebSearchResponse(query=query, configured=self.is_configured(), results=[])

        if not self.is_configured():
            return WebSearchResponse(query=normalized_query, configured=False, results=[])

        payload = json.dumps(
            {
                "query": normalized_query,
                "search_depth": "basic",
                "include_answer": True,
                "include_raw_content": False,
                "max_results": max(1, min(max_results, 8)),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            url=settings.tavily_endpoint,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {settings.tavily_api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=settings.external_tool_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Tavily search failed: {exc.code} {detail}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Tavily search failed: {exc}") from exc

        results = [
            WebSearchResult(
                title=str(item.get("title") or "Untitled result"),
                url=str(item.get("url") or ""),
                content=str(item.get("content") or item.get("raw_content") or ""),
                score=float(item["score"]) if item.get("score") is not None else None,
            )
            for item in data.get("results", [])
            if item.get("url")
        ]
        return WebSearchResponse(
            query=normalized_query,
            answer=data.get("answer"),
            results=results,
            configured=True,
        )


web_search_service = WebSearchService()
