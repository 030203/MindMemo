from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    timezone: str
    notify_channels: list[str] = Field(default_factory=list)


class SettingsUpdateRequest(BaseModel):
    notify_channels: list[str] | None = None
    timezone: str | None = None


class NotificationProviderStatus(BaseModel):
    channel: str
    configured: bool


class NotificationTestRequest(BaseModel):
    channel: str


class NotificationTestResponse(BaseModel):
    channel: str
    sent: bool
