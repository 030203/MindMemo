from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from app.core.config import settings
from app.schemas.external_tools import WeatherResponse


class WeatherService:
    def is_configured(self) -> bool:
        return bool(settings.openweather_api_key)

    def current_weather(self, location: str) -> WeatherResponse:
        display_location = location.strip()
        normalized_location = self._normalize_location(display_location)
        if not normalized_location:
            return WeatherResponse(location=location, description="请先提供城市或地点。", configured=self.is_configured())

        if not self.is_configured():
            return WeatherResponse(location=normalized_location, description="OpenWeather API key 未配置。", configured=False)

        params = urllib.parse.urlencode(
            {
                "q": normalized_location,
                "appid": settings.openweather_api_key,
                "units": "metric",
                "lang": "zh_cn",
            }
        )
        request = urllib.request.Request(
            url=f"{settings.openweather_current_endpoint}?{params}",
            method="GET",
        )

        try:
            with urllib.request.urlopen(request, timeout=settings.external_tool_timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenWeather request failed: {exc.code} {detail}") from exc
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"OpenWeather request failed: {exc}") from exc

        weather_items = data.get("weather") or []
        main = data.get("main") or {}
        wind = data.get("wind") or {}
        description = str(weather_items[0].get("description") if weather_items else "天气信息暂缺")
        return WeatherResponse(
            location=display_location or str(data.get("name") or normalized_location),
            description=description,
            temperature_c=self._float_or_none(main.get("temp")),
            feels_like_c=self._float_or_none(main.get("feels_like")),
            humidity=int(main["humidity"]) if main.get("humidity") is not None else None,
            wind_speed_mps=self._float_or_none(wind.get("speed")),
            configured=True,
        )

    def _float_or_none(self, value) -> float | None:
        if value is None:
            return None

    def _normalize_location(self, location: str) -> str:
        aliases = {
            "北京": "Beijing",
            "上海": "Shanghai",
            "深圳": "Shenzhen",
            "广州": "Guangzhou",
            "杭州": "Hangzhou",
            "成都": "Chengdu",
            "武汉": "Wuhan",
            "南京": "Nanjing",
            "重庆": "Chongqing",
            "天津": "Tianjin",
            "苏州": "Suzhou",
        }
        return aliases.get(location.strip(), location.strip())
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


weather_service = WeatherService()
