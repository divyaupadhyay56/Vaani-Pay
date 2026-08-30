import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class Settings:
    GROK_API_KEY: str = os.getenv("GROK_API_KEY", "")
    GROK_MODEL: str = os.getenv("GROK_MODEL", "grok-4.6")
    GROK_BASE_URL: str = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1")

    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    USE_REDIS: bool = os.getenv("USE_REDIS", "false").lower() == "true"

    CONFIDENCE_THRESHOLD: float = 0.55
    DB_PATH: str = os.getenv("DB_PATH", "") 

    SESSION_TTL_HOURS: int = int(os.getenv("SESSION_TTL_HOURS", "24"))

    CORS_ALLOWED_ORIGINS: str = os.getenv("CORS_ALLOWED_ORIGINS", "")
    TABBY_BASE_URL: str = os.getenv("TABBY_BASE_URL", "https://api.tabby.ai")
    TABBY_PUBLIC_KEY: str = os.getenv("TABBY_PUBLIC_KEY", "")
    TABBY_SECRET_KEY: str = os.getenv("TABBY_SECRET_KEY", "")
    TABBY_MERCHANT_CODE: str = os.getenv("TABBY_MERCHANT_CODE", "")


settings = Settings()
