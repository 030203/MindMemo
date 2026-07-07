"""
WebSearchTool + WeatherTool 单元测试

测试覆盖:
  WebSearch:
    1. 正常搜索 → 返回结果
    2. API不可用 → success=False
  Weather:
    1. 北京今天 → 返回天气数据
    2. API不可用 → success=False
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest


def _mock_httpx_response(status_code: int, json_data: dict) -> AsyncMock:
    """构造 httpx.Response mock"""
    r = AsyncMock()
    r.status_code = status_code
    r.json = AsyncMock(return_value=json_data)
    # text 属性 (错误输出时用到)
    r.text = f"mock http {status_code}"
    return r


def _patch_httpx(method: str, return_value, side_effect=None):
    """
    Mock httpx.AsyncClient 的 async context manager 行为.
    method: "post" | "get"
    """
    mock_instance = AsyncMock()
    setattr(mock_instance, method, AsyncMock(
        return_value=return_value, side_effect=side_effect
    ))

    # 让 `async with httpx.AsyncClient() as client:` 返回 mock_instance
    mock_context = MagicMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_context.__aexit__ = AsyncMock(return_value=None)

    return patch("httpx.AsyncClient", return_value=mock_context), mock_instance


# ================================================================
# WebSearchTool
# ================================================================

class TestWebSearchTool:
    def test_normal_search(self):
        """
        测试要点 1: 正常搜索 → 返回结果列表
        """
        from app.tools.external.web_search import WebSearchTool

        mock_resp = _mock_httpx_response(200, {
            "results": [
                {
                    "title": "Python Closure",
                    "url": "https://example.com/closure",
                    "content": "A closure in Python is...",
                    "published_date": "2026-01-15",
                },
            ]
        })

        patcher, _ = _patch_httpx("post", mock_resp)
        with patcher:
            result = asyncio.run(
                WebSearchTool().execute(query="Python closure", api_key="test-key")
            )

        assert result.success is True, f"error={result.error}"
        assert len(result.data["results"]) == 1
        assert result.data["results"][0]["title"] == "Python Closure"

    def test_empty_query(self):
        """空 query → success=False"""
        from app.tools.external.web_search import WebSearchTool

        result = asyncio.run(WebSearchTool().execute(query="", api_key="test"))
        assert result.success is False
        assert "query" in result.error

    def test_no_api_key(self):
        """无 API key → success=False"""
        from app.tools.external.web_search import WebSearchTool
        from app.core import config

        with patch.object(config.settings, "tavily_api_key", None):
            result = asyncio.run(WebSearchTool().execute(query="Python"))
        assert result.success is False
        assert "API key" in result.error

    def test_api_timeout(self):
        """
        测试要点 2: API 超时 → success=False
        """
        from app.tools.external.web_search import WebSearchTool

        import httpx
        patcher, _ = _patch_httpx("post", None, side_effect=httpx.TimeoutException("timeout"))
        with patcher:
            result = asyncio.run(
                WebSearchTool().execute(query="Python", api_key="test")
            )

        assert result.success is False
        assert "超时" in result.error

    def test_register(self):
        from app.tools.registry import ToolRegistry
        from app.tools.external.web_search import WebSearchTool

        registry = ToolRegistry()
        registry.register(WebSearchTool)
        tool = registry.get_tool("web_search")
        assert tool is not None

    def test_schema(self):
        from app.tools.external.web_search import WebSearchTool

        schema = WebSearchTool().to_json_schema()
        assert schema["name"] == "web_search"
        assert "query" in schema["parameters"]["required"]


# ================================================================
# WeatherTool
# ================================================================

class TestWeatherTool:
    def test_normal_weather(self):
        """
        测试要点 1: 正常查询 → 返回天气数据
        """
        from app.tools.external.weather import WeatherTool

        mock_resp = _mock_httpx_response(200, {
            "name": "北京",
            "sys": {"country": "CN"},
            "main": {
                "temp": 28.5, "feels_like": 29.0,
                "temp_min": 25.0, "temp_max": 32.0,
                "humidity": 55, "pressure": 1013,
            },
            "weather": [{"id": 800, "description": "晴", "icon": "01d"}],
            "wind": {"speed": 3.5},
            "visibility": 10000,
        })

        patcher, _ = _patch_httpx("get", mock_resp)
        with patcher:
            result = asyncio.run(
                WeatherTool().execute(city="北京", api_key="test-key")
            )

        assert result.success is True, f"error={result.error}"
        assert result.data["city"] == "北京"
        assert result.data["temperature"]["current"] == 28.5
        assert result.data["condition"] == "晴"
        assert "户外活动" in result.data.get("suggestion", "")

    def test_rainy_weather(self):
        """降雨天气 → 建议带伞"""
        from app.tools.external.weather import WeatherTool

        mock_resp = _mock_httpx_response(200, {
            "name": "上海",
            "sys": {"country": "CN"},
            "main": {"temp": 20.0, "feels_like": 19.0, "temp_min": 18.0, "temp_max": 22.0, "humidity": 80, "pressure": 1010},
            "weather": [{"id": 500, "description": "小雨", "icon": "10d"}],
            "wind": {"speed": 2.0},
            "visibility": 5000,
        })

        patcher, _ = _patch_httpx("get", mock_resp)
        with patcher:
            result = asyncio.run(
                WeatherTool().execute(city="上海", api_key="test")
            )

        assert result.success is True
        assert "带伞" in result.data.get("suggestion", "")

    def test_empty_city(self):
        """空城市 → success=False"""
        from app.tools.external.weather import WeatherTool

        result = asyncio.run(WeatherTool().execute(city=""))
        assert result.success is False

    def test_no_api_key(self):
        """无 API key → success=False"""
        from app.tools.external.weather import WeatherTool
        from app.core import config

        with patch.object(config.settings, "openweather_api_key", None):
            result = asyncio.run(WeatherTool().execute(city="北京"))
        assert result.success is False
        assert "API key" in result.error

    def test_register(self):
        from app.tools.registry import ToolRegistry
        from app.tools.external.weather import WeatherTool

        registry = ToolRegistry()
        registry.register(WeatherTool)
        tool = registry.get_tool("weather")
        assert tool is not None

    def test_schema(self):
        from app.tools.external.weather import WeatherTool

        schema = WeatherTool().to_json_schema()
        assert schema["name"] == "weather"
        assert "city" in schema["parameters"]["required"]
