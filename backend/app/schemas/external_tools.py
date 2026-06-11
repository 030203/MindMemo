from pydantic import BaseModel, Field


class WebSearchRequest(BaseModel):
    query: str
    max_results: int = 5


class WebSearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float | None = None


class WebSearchResponse(BaseModel):
    query: str
    answer: str | None = None
    results: list[WebSearchResult] = Field(default_factory=list)
    provider: str = "tavily"
    configured: bool = False


class WeatherRequest(BaseModel):
    location: str


class WeatherResponse(BaseModel):
    location: str
    description: str
    temperature_c: float | None = None
    feels_like_c: float | None = None
    humidity: int | None = None
    wind_speed_mps: float | None = None
    provider: str = "openweather"
    configured: bool = False
