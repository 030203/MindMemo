from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "MindMemo API"
    app_env: str = "dev"
    api_prefix: str = "/api/v1"
    frontend_origin: str = "http://127.0.0.1:6100"
    database_url: str = "sqlite:///./data/mysecondbrain_dev.db"
    jwt_secret: str = "replace-this-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    refresh_token_expire_minutes: int = 60 * 24 * 30
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    embedding_provider: str = "local_hash"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536
    embedding_signature: str = "local_hash_v3"
    embedding_timeout_seconds: float = 10.0
    llm_request_timeout_seconds: float = 20.0
    llm_max_completion_tokens: int = 700
    insight_cache_ttl_seconds: int = 60
    allow_dev_demo_user: bool = False
    reminder_scan_interval_seconds: int = 60
    reminder_notification_enabled: bool = True
    reminder_notification_timeout_seconds: float = 10.0
    pushdeer_endpoint: str = "https://api2.pushdeer.com/message/push"
    pushdeer_pushkey: str | None = None
    wecom_webhook_url: str | None = None
    serverchan_sendkey: str | None = None
    serverchan_endpoint_base: str = "https://sctapi.ftqq.com"
    tavily_api_key: str | None = None
    tavily_endpoint: str = "https://api.tavily.com/search"
    openweather_api_key: str | None = None
    openweather_current_endpoint: str = "https://api.openweathermap.org/data/2.5/weather"
    external_tool_timeout_seconds: float = 12.0
    upload_root: str = "uploads"
    max_image_upload_bytes: int = 10 * 1024 * 1024

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
