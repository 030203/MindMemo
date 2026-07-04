"""
WeatherTool - 天气查询工具 (OpenWeather API)

职责：查询指定城市的天气信息

============================================================
内部处理流程:
============================================================

[步骤1] 接收参数
  city: str              # 城市名
  date: str = "today"    # today / tomorrow

[步骤2] 调用 OpenWeather API
  GET api.openweathermap.org/data/2.5/weather?q={city}&appid={key}&units=metric&lang=zh_cn
  超时 10s

[步骤3] 格式化结果

[步骤4] 返回 ToolResult

============================================================
测试要点:
  1. 北京今天 → 返回天气数据
  2. API不可用 → success=False, 不崩溃
============================================================
"""
from __future__ import annotations

import httpx

from app.tools.base import BaseTool, ToolResult, ToolParameter, ToolParameterType

_OWM_URL = "https://api.openweathermap.org/data/2.5/weather"
_OWM_GEO_URL = "https://api.openweathermap.org/geo/1.0/direct"
_TIMEOUT = 10.0

# weather condition codes → 简短中文描述
_CONDITIONS_ZH: dict[int, str] = {
    200: "雷阵雨", 201: "雷阵雨", 300: "小雨", 301: "小雨",
    500: "阵雨", 501: "中雨", 502: "大雨",
    600: "小雪", 601: "中雪", 602: "大雪",
    701: "雾", 711: "霾",
    800: "晴", 801: "少云", 802: "多云", 803: "阴", 804: "阴",
}


def _to_condition(weather_id: int) -> str:
    return _CONDITIONS_ZH.get(weather_id, "未知")


class WeatherTool(BaseTool):
    """
    天气查询工具 — 通过 OpenWeather API 获取城市天气

    用于 Agent 在对话中回答天气相关问题。
    """

    name: str = "weather"
    description: str = (
        "查询指定城市的最新天气信息。"
        "输入城市名称(中文或英文)，返回温度/天气状况/湿度等信息。"
    )
    parameters: list[ToolParameter] = [
        ToolParameter(
            name="city",
            type=ToolParameterType.STRING,
            description="城市名称，如'北京'、'beijing'",
            required=True,
        ),
        ToolParameter(
            name="date",
            type=ToolParameterType.STRING,
            description="日期，目前仅支持'today'(默认)",
            required=False,
            default="today",
        ),
    ]

    async def execute(self, **kwargs) -> ToolResult:
        # [步骤1] 接收参数
        city: str = kwargs.get("city", "")
        if not city or not city.strip():
            return ToolResult(success=False, error="city 不能为空")

        api_key: str | None = kwargs.get("api_key")
        if api_key is None:
            from app.core.config import settings
            api_key = getattr(settings, "openweather_api_key", None)
        if not api_key:
            return ToolResult(
                success=False,
                error="缺少 OpenWeather API key。请在 .env 中配置 OPENWEATHER_API_KEY 或通过 kwargs 传入",
            )

        # [步骤2] 调用 OpenWeather API
        try:
            async with httpx.AsyncClient() as client:
                # [步骤2a] 先用 Geocoding API 把城市名（支持中文）解析为坐标
                #   OpenWeather 的 /data/2.5/weather?q= 不能识别中文城市名（返回 404），
                #   必须先经 /geo/1.0/direct 得到经纬度再查天气。
                query_params: dict = {
                    "q": city.strip(),
                    "appid": api_key,
                    "units": "metric",
                    "lang": "zh_cn",
                }
                try:
                    geo_resp = await client.get(
                        _OWM_GEO_URL,
                        params={"q": city.strip(), "appid": api_key, "limit": 1},
                        timeout=_TIMEOUT,
                    )
                    if geo_resp.status_code == 200:
                        geo_data = geo_resp.json()
                        if isinstance(geo_data, list) and geo_data:
                            query_params = {
                                "lat": geo_data[0].get("lat"),
                                "lon": geo_data[0].get("lon"),
                                "appid": api_key,
                                "units": "metric",
                                "lang": "zh_cn",
                            }
                except httpx.TimeoutException:
                    return ToolResult(success=False, error="OpenWeather Geocoding 请求超时")

                # [步骤2b] 查询天气（优先用坐标，解析失败时退回 q= 城市名）
                resp = await client.get(
                    _OWM_URL,
                    params=query_params,
                    timeout=_TIMEOUT,
                )
                if resp.status_code != 200:
                    return ToolResult(
                        success=False,
                        error=f"OpenWeather API 返回 {resp.status_code}: {resp.text[:200]}",
                    )
                data = resp.json()
        except httpx.TimeoutException:
            return ToolResult(success=False, error="OpenWeather API 请求超时")
        except Exception as exc:
            return ToolResult(success=False, error=f"天气查询失败: {exc}")

        # [步骤3] 格式化
        main = data.get("main", {})
        weather_list = data.get("weather", [])
        weather = weather_list[0] if weather_list else {}
        wind = data.get("wind", {})

        condition_id = weather.get("id", 800)

        result_data = {
            "city": data.get("name", city),
            "country": data.get("sys", {}).get("country", ""),
            "temperature": {
                "current": main.get("temp"),
                "feels_like": main.get("feels_like"),
                "min": main.get("temp_min"),
                "max": main.get("temp_max"),
            },
            "condition": _to_condition(condition_id),
            "description": weather.get("description", ""),
            "humidity": main.get("humidity"),
            "pressure": main.get("pressure"),
            "wind_speed": wind.get("speed"),
            "visibility": data.get("visibility"),
        }

        # 简单建议
        temp = main.get("temp")
        if temp is not None:
            if temp > 35:
                result_data["suggestion"] = "高温天气，注意防暑降温"
            elif temp < 5:
                result_data["suggestion"] = "天气寒冷，注意保暖"
            elif condition_id >= 500 and condition_id < 600:
                result_data["suggestion"] = "有降雨，建议带伞"
            elif 10 <= temp <= 30 and condition_id == 800:
                result_data["suggestion"] = "天气舒适，适合户外活动"
            else:
                result_data["suggestion"] = ""

        # [步骤4] 返回
        return ToolResult(success=True, data=result_data)
