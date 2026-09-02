import os
import sqlite3  # noqa: F401  — exposed so callers can catch sqlite3.IntegrityError via db.sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DB_PATH", str(PROJECT_ROOT / "vaani_pay.db")))

from app.db.connection import get_connection, tx  # noqa: E402
from app.db.schema import SCHEMA  # noqa: E402
from app.db.seed import init_db  # noqa: E402

__all__ = ["sqlite3", "DB_PATH", "get_connection", "tx", "SCHEMA", "init_db"]
