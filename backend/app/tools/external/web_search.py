"""
WebSearchTool - 网络搜索工具 (Tavily API)

职责：调用 Tavily 搜索 API，为 Agent 提供实时网络信息

============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  query: str              # 搜索关键词
  max_results: int = 5    # 返回结果数

[步骤2] 调用 Tavily API
  POST https://api.tavily.com/search
  超时 10s，重试最多 1 次

[步骤3] 结果格式化
  每条: {title, url, snippet(来自content), published_date}

[步骤4] 返回 ToolResult

============================================================
测试要点:
  1. 正常搜索: "Python" → 返回结果列表
  2. API不可用 → success=False, 不崩溃
============================================================
"""
from __future__ import annotations

import httpx

from app.tools.base import BaseTool, ToolResult, ToolParameter, ToolParameterType

_TAVILY_URL = "https://api.tavily.com/search"
_TIMEOUT = 10.0


class WebSearchTool(BaseTool):
    """
    网络搜索工具 — 通过 Tavily API 搜索实时网络信息

    用于 Agent 需要补充外部信息时调用，如技术查新、实时资讯。
    """

    name: str = "web_search"
    description: str = (
        "搜索网络获取实时信息。适用于查找最新动态、技术文档、新闻等。"
        "输入搜索关键词，返回标题/链接/摘要列表。"
    )
    parameters: list[ToolParameter] = [
        ToolParameter(
            name="query",
            type=ToolParameterType.STRING,
            description="搜索查询词",
            required=True,
        ),
        ToolParameter(
            name="max_results",
            type=ToolParameterType.INTEGER,
            description="最大返回结果数，默认 5",
            required=False,
            default=5,
        ),
    ]

    async def execute(self, **kwargs) -> ToolResult:
        # [步骤1] 接收参数
        query: str = kwargs.get("query", "")
        max_results: int = kwargs.get("max_results", 5)

        if not query or not query.strip():
            return ToolResult(success=False, error="query 不能为空")

        api_key: str | None = kwargs.get("api_key")
        if api_key is None:
            # 尝试从配置读取
            from app.core.config import settings
            api_key = getattr(settings, "tavily_api_key", None)

        if not api_key:
            return ToolResult(
                success=False,
                error="缺少 Tavily API key。请在 .env 中配置 TAVILY_API_KEY 或通过 kwargs 传入",
            )

        # [步骤2] 调用 Tavily API
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    _TAVILY_URL,
                    json={
                        "query": query.strip(),
                        "api_key": api_key,
                        "max_results": max(max_results, 1),
                    },
                    timeout=_TIMEOUT,
                )
                if resp.status_code != 200:
                    return ToolResult(
                        success=False,
                        error=f"Tavily API 返回 {resp.status_code}: {resp.text[:200]}",
                    )
                data = resp.json()
        except httpx.TimeoutException:
            return ToolResult(success=False, error="Tavily API 请求超时")
        except Exception as exc:
            return ToolResult(success=False, error=f"网络搜索失败: {exc}")

        # [步骤3] 结果格式化
        results = []
        for r in data.get("results", [])[:max_results]:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": (r.get("content") or "")[:300],
                "published_date": r.get("published_date"),
            })

        # [步骤4] 返回
        return ToolResult(
            success=True,
            data={
                "results": results,
                "query": query.strip(),
                "total_results": len(results),
            },
        )
