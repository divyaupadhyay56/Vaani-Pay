from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

_local = threading.local()


def get_connection() -> sqlite3.Connection:
    import app.db as db_pkg
    db_path = str(db_pkg.DB_PATH)
    conn = getattr(_local, "conn", None)
    current_path = getattr(_local, "conn_path", None)

    if conn is None or current_path != db_path:
        if conn is not None:
            conn.close()
        db_path_obj = db_pkg.DB_PATH
        db_path_obj.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path_obj, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
        _local.conn_path = db_path
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
