import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


class Settings:
    # LLM — xAI Grok API (OpenAI-compatible endpoint)
    GROK_API_KEY: str = os.getenv("GROK_API_KEY", "")
    GROK_MODEL: str = os.getenv("GROK_MODEL", "grok-4.6")
    GROK_BASE_URL: str = os.getenv("GROK_BASE_URL", "https://api.x.ai/v1")

    # Session store (WebSocket per-connection conversation state — separate
    # from the DB-backed auth sessions in app/auth.py / app/db.py)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    USE_REDIS: bool = os.getenv("USE_REDIS", "false").lower() == "true"

    # Confidence threshold below which the agent hands off to a human
    CONFIDENCE_THRESHOLD: float = 0.55

    # Database
    DB_PATH: str = os.getenv("DB_PATH", "")  # empty = default path in app/db.py

    # Auth
    SESSION_TTL_HOURS: int = int(os.getenv("SESSION_TTL_HOURS", "24"))

    # CORS — comma-separated list of allowed origins. Empty = safe localhost
    # defaults only (see app/main.py). Never defaults to "*" with credentials.
    CORS_ALLOWED_ORIGINS: str = os.getenv("CORS_ALLOWED_ORIGINS", "")

    # Tabby (BNPL) — standalone client only (app/tabby_client.py), not wired
    # into any route or flow yet. See that module's docstring.
    TABBY_BASE_URL: str = os.getenv("TABBY_BASE_URL", "https://api.tabby.ai")
    TABBY_PUBLIC_KEY: str = os.getenv("TABBY_PUBLIC_KEY", "")
    TABBY_SECRET_KEY: str = os.getenv("TABBY_SECRET_KEY", "")
    TABBY_MERCHANT_CODE: str = os.getenv("TABBY_MERCHANT_CODE", "")


settings = Settings()
