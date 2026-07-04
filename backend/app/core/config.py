import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Locate the .env file relative to THIS file (backend/app/core/config.py)
# config.py is at:  backend/app/core/config.py
# .env is at:      backend/.env
_ENV_DIR = Path(__file__).resolve().parent.parent.parent
_ENV_PATH = _ENV_DIR / ".env"

# STEP 1: FORCE-LOAD .env into os.environ, OVERRIDING any existing env vars
# This guarantees that pydantic-settings picks up the file's values regardless
# of CWD or stale system env vars.
load_dotenv(_ENV_PATH, override=True)


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
    llm_request_timeout_seconds: float = 60.0
    llm_max_completion_tokens: int = 4096

    # LLM provider 选择: "xiaomi"(默认, 用 xiaomi_*) | "deepseek"(用 openai_*)
    llm_provider: str = "xiaomi"
    # 用户可见回答的 LLM provider (chat / chat_with_system)
    # 未设置时回退到 llm_provider（向后兼容）
    llm_user_facing_provider: str = ""
    # 用户可见回答所使用的模型名
    llm_user_facing_model: str = "mimo-v2.5"
    # 小米 MiMo: 独立 base_url / 模型 / 多 key 轮询(逗号分隔)
    xiaomi_base_url: str | None = None
    xiaomi_model: str = "mimo-v2.5"
    xiaomi_api_keys: str | None = None
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
    openweather_api_key: str | None = None
    upload_root: str = "uploads"
    max_image_upload_bytes: int = 10 * 1024 * 1024

    @property
    def xiaomi_key_list(self) -> list[str]:
        """把逗号分隔的 xiaomi_api_keys 解析成列表(去空白/去空项)。"""
        if not self.xiaomi_api_keys:
            return []
        return [k.strip() for k in self.xiaomi_api_keys.split(",") if k.strip()]

    model_config = SettingsConfigDict(
        env_file=str(_ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
