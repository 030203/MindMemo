from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    timezone: str
    llm_provider: str
    llm_model: str
    web_search_enabled: bool
    notify_channels: list[str] = Field(default_factory=list)


class SettingsUpdateRequest(BaseModel):
    notify_channels: list[str] | None = None


class NotificationProviderStatus(BaseModel):
    channel: str
    configured: bool


class NotificationTestRequest(BaseModel):
    channel: str


class NotificationTestResponse(BaseModel):
    channel: str
    sent: bool
