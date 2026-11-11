from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration. Every secret comes from environment variables (see .env.example)."""

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    APP_ENV: str = "development"
    SECRET_KEY: str = "dev-secret-change-me"
    TZ: str = "Asia/Kolkata"
    FRONTEND_URL: str = "http://localhost:5173"
    CORS_ORIGINS: str = "http://localhost:5173"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = "postgresql+psycopg://smartstock:smartstock@localhost:5433/smartstock"
    TEST_DATABASE_URL: str = "postgresql+psycopg://smartstock:smartstock@localhost:5433/smartstock_test"
    REDIS_URL: str = "redis://localhost:6379/0"

    ACCESS_TOKEN_MINUTES: int = 30
    REFRESH_TOKEN_DAYS: int = 7
    LOGIN_RATE_LIMIT_PER_MINUTE: int = 10

    STORAGE_DIR: str = "data"
    BACKUP_DIR: str = "../backups"
    BACKUP_KEEP: int = 14

    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = False
    SMTP_FROM: str = "SmartStock RPA <noreply@smartstock.local>"
    EMAIL_ASYNC: bool = True  # queue emails on Celery (sync fallback when the broker is down)

    TELEGRAM_BOT_TOKEN: str = ""

    LLM_PROVIDER: str = "none"
    LLM_TIMEOUT_SECONDS: int = 30
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = ""
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    IMAP_HOST: str = ""
    IMAP_PORT: int = 993
    IMAP_USER: str = ""
    IMAP_PASSWORD: str = ""
    IMAP_FOLDER: str = "INBOX"

    TESSERACT_CMD: str = "tesseract"
    COURIER_PROVIDER: str = "mock"
    SHIPROCKET_BASE_URL: str = "https://apiv2.shiprocket.in/v1/external"
    SHIPROCKET_EMAIL: str = ""
    SHIPROCKET_PASSWORD: str = ""

    @field_validator("LLM_PROVIDER")
    @classmethod
    def _provider(cls, v: str) -> str:
        v = (v or "none").strip().lower()
        if v not in {"none", "ollama", "anthropic", "openai"}:
            raise ValueError("LLM_PROVIDER must be none, ollama, anthropic or openai")
        return v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_test(self) -> bool:
        return self.APP_ENV == "test"

    @property
    def storage_path(self) -> Path:
        p = Path(self.STORAGE_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def storage_subdir(self, name: str) -> Path:
        p = self.storage_path / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def imap_enabled(self) -> bool:
        return bool(self.IMAP_HOST and self.IMAP_USER)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.TELEGRAM_BOT_TOKEN)

    @property
    def courier_enabled(self) -> bool:
        return self.COURIER_PROVIDER.strip().lower() == "shiprocket" and bool(self.SHIPROCKET_EMAIL and self.SHIPROCKET_PASSWORD)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
