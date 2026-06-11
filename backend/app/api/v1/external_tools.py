from fastapi import APIRouter, Depends

from app.core.deps import get_current_user_id
from app.schemas.common import ApiResponse
from app.schemas.external_tools import WeatherRequest, WeatherResponse, WebSearchRequest, WebSearchResponse
from app.services.weather_service import weather_service
from app.services.web_search_service import web_search_service

router = APIRouter()


@router.post("/web-search")
def web_search(payload: WebSearchRequest, _user_id=Depends(get_current_user_id)) -> ApiResponse[WebSearchResponse]:
    try:
        data = web_search_service.search(payload.query, payload.max_results)
    except RuntimeError as exc:
        data = WebSearchResponse(query=payload.query, answer=str(exc), results=[], configured=web_search_service.is_configured())
    return ApiResponse(data=data)


@router.post("/weather")
def current_weather(payload: WeatherRequest, _user_id=Depends(get_current_user_id)) -> ApiResponse[WeatherResponse]:
    try:
        data = weather_service.current_weather(payload.location)
    except RuntimeError as exc:
        data = WeatherResponse(location=payload.location, description=str(exc), configured=weather_service.is_configured())
    return ApiResponse(data=data)
