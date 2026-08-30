

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DB_PATH", str(PROJECT_ROOT / "vaani_pay.db")))
_SEED_DATA_DIR = PROJECT_ROOT / "mcp_server" / "data"

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    phone           TEXT,
    password_hash   TEXT NOT NULL,
    language        TEXT NOT NULL DEFAULT 'en',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    last_login      TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token           TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS chat_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,
    message         TEXT NOT NULL,
    timestamp       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_history_user ON chat_history(user_id, conversation_id);

CREATE TABLE IF NOT EXISTS payments (
    payment_id      TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,
    amount          REAL NOT NULL,
    method          TEXT,
    failure_reason  TEXT,
    date            TEXT
);
CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);

CREATE TABLE IF NOT EXISTS orders (
    order_id        TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status          TEXT NOT NULL,
    total           REAL NOT NULL,
    items           TEXT NOT NULL,  -- JSON-encoded list of strings
    date            TEXT
);
CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id);

CREATE TABLE IF NOT EXISTS refunds (
    refund_id       TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    payment_id      TEXT,
    amount          REAL NOT NULL,
    status          TEXT NOT NULL,
    date            TEXT
);
CREATE INDEX IF NOT EXISTS idx_refunds_user ON refunds(user_id);

CREATE TABLE IF NOT EXISTS transactions (
    txn_id          TEXT NOT NULL,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,
    amount          REAL NOT NULL,
    status          TEXT NOT NULL,
    date            TEXT,
    PRIMARY KEY (txn_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);

-- ================== Wallet: real money-movement system ==================
-- (payment_accounts / wallet_transactions / beneficiaries)
-- Separate from the legacy payments/orders/refunds/transactions tables
-- above, which remain untouched (existing mock "payment gateway" demo
-- data + tools). This is the new, real ledger: every rupee added or
-- transferred through Add Money / Send Money goes through here, and the
-- balance is always DERIVED from this ledger by the backend — never
-- written directly by the frontend or the AI.

CREATE TABLE IF NOT EXISTS payment_accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    payment_id      TEXT NOT NULL UNIQUE,
    account_number  TEXT NOT NULL UNIQUE,
    ifsc            TEXT NOT NULL,
    balance         REAL NOT NULL DEFAULT 0,
    currency        TEXT NOT NULL DEFAULT 'INR',
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payment_accounts_number ON payment_accounts(account_number);

CREATE TABLE IF NOT EXISTS wallet_transactions (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id              TEXT NOT NULL UNIQUE,
    sender_account_id           INTEGER REFERENCES payment_accounts(id) ON DELETE SET NULL,
    receiver_account_id         INTEGER REFERENCES payment_accounts(id) ON DELETE SET NULL,
    amount                      REAL NOT NULL,
    transaction_type            TEXT NOT NULL,  -- CREDIT | TRANSFER_OUT | TRANSFER_IN
    status                      TEXT NOT NULL,  -- PENDING | SUCCESS | FAILED | CANCELLED
    description                 TEXT,
    -- Snapshots taken at transaction time, so a party's transaction
    -- history stays meaningful even if the other account is later
    -- deleted (see ON DELETE SET NULL above), and so external/simulated
    -- recipients (not in our system) still show a clear name/number.
    sender_name                 TEXT,
    receiver_name                TEXT,
    recipient_account_number    TEXT,
    recipient_ifsc               TEXT,
    failure_reason               TEXT,
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wallet_txn_sender ON wallet_transactions(sender_account_id);
CREATE INDEX IF NOT EXISTS idx_wallet_txn_receiver ON wallet_transactions(receiver_account_id);

CREATE TABLE IF NOT EXISTS beneficiaries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_name  TEXT NOT NULL,
    account_number  TEXT NOT NULL,
    ifsc            TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE(user_id, account_number)
);
CREATE INDEX IF NOT EXISTS idx_beneficiaries_user ON beneficiaries(user_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    """One connection per thread (sqlite3 connections aren't thread-safe to share)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """Context manager for a write transaction: commits on success, rolls back on error."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db(seed_if_empty: bool = True) -> None:
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()

    if seed_if_empty:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        if row["c"] == 0:
            _seed_from_legacy_json(conn)


def _seed_from_legacy_json(conn: sqlite3.Connection) -> None:
    
    from app.security import hash_password 

    users_path = _SEED_DATA_DIR / "users.json"
    if not users_path.exists():
        return

    with open(users_path, "r", encoding="utf-8") as f:
        legacy_users = json.load(f)

    now = _now()
    demo_password_hash = hash_password("Demo@1234")
    for uid, u in legacy_users.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (id, name, email, phone, password_hash, language, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, u["name"], u["email"], u.get("phone"), demo_password_hash, "en", now, now),
        )

    def _load(name: str) -> dict:
        p = _SEED_DATA_DIR / name
        if not p.exists():
            return {}
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    for pid, p in _load("payments.json").items():
        conn.execute(
            "INSERT OR IGNORE INTO payments (payment_id, user_id, status, amount, method, failure_reason, date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pid, p["user_id"], p["status"], p["amount"], p.get("method"), p.get("failure_reason"), p.get("date")),
        )

    for oid, o in _load("orders.json").items():
        conn.execute(
            "INSERT OR IGNORE INTO orders (order_id, user_id, status, total, items, date) VALUES (?, ?, ?, ?, ?, ?)",
            (oid, o["user_id"], o["status"], o["total"], json.dumps(o.get("items", [])), o.get("date")),
        )

    for rid, r in _load("refunds.json").items():
        conn.execute(
            "INSERT OR IGNORE INTO refunds (refund_id, user_id, payment_id, amount, status, date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (rid, r["user_id"], r.get("payment_id"), r["amount"], r["status"], r.get("date")),
        )

    for uid, txns in _load("transactions.json").items():
        for t in txns:
            conn.execute(
                "INSERT OR IGNORE INTO transactions (txn_id, user_id, type, amount, status, date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (t["txn_id"], uid, t["type"], t["amount"], t["status"], t.get("date")),
            )

    from app import wallet  
    accounts = {}
    for uid in legacy_users.keys():
        accounts[uid] = wallet.insert_account_row(conn, uid)

    demo_uids = list(legacy_users.keys())
    if len(demo_uids) >= 2:
        u1, u2 = demo_uids[0], demo_uids[1]
        acc1_id = conn.execute("SELECT id FROM payment_accounts WHERE user_id = ?", (u1,)).fetchone()["id"]
        acc2_id = conn.execute("SELECT id FROM payment_accounts WHERE user_id = ?", (u2,)).fetchone()["id"]
        acc1_num = accounts[u1]["account_number"]
        acc2_num = accounts[u2]["account_number"]

        conn.execute("UPDATE payment_accounts SET balance = 8500 WHERE id = ?", (acc1_id,))
        conn.execute("UPDATE payment_accounts SET balance = 8000 WHERE id = ?", (acc2_id,))

        conn.execute(
            "INSERT INTO wallet_transactions (transaction_id, sender_account_id, receiver_account_id, amount, "
            "transaction_type, status, description, sender_name, receiver_name, created_at, updated_at) "
            "VALUES (?, NULL, ?, 10000, 'CREDIT', 'SUCCESS', 'Wallet top-up', 'Self (Add Money)', 'Self (Add Money)', ?, ?)",
            (wallet.generate_transaction_id(), acc1_id, now, now),
        )
        conn.execute(
            "INSERT INTO wallet_transactions (transaction_id, sender_account_id, receiver_account_id, amount, "
            "transaction_type, status, description, sender_name, receiver_name, created_at, updated_at) "
            "VALUES (?, NULL, ?, 6500, 'CREDIT', 'SUCCESS', 'Wallet top-up', 'Self (Add Money)', 'Self (Add Money)', ?, ?)",
            (wallet.generate_transaction_id(), acc2_id, now, now),
        )

        u1_name = legacy_users[u1]["name"]
        u2_name = legacy_users[u2]["name"]
        conn.execute(
            "INSERT INTO wallet_transactions (transaction_id, sender_account_id, receiver_account_id, amount, "
            "transaction_type, status, description, sender_name, receiver_name, recipient_account_number, recipient_ifsc, created_at, updated_at) "
            "VALUES (?, ?, ?, 1500, 'TRANSFER_OUT', 'SUCCESS', 'Demo transfer', 'You', ?, ?, ?, ?, ?)",
            (wallet.generate_transaction_id(), acc1_id, acc2_id, u2_name, acc2_num, wallet.FIXED_IFSC, now, now),
        )
        conn.execute(
            "INSERT INTO wallet_transactions (transaction_id, sender_account_id, receiver_account_id, amount, "
            "transaction_type, status, description, sender_name, receiver_name, created_at, updated_at) "
            "VALUES (?, ?, ?, 1500, 'TRANSFER_IN', 'SUCCESS', 'Demo transfer', ?, ?, ?, ?)",
            (wallet.generate_transaction_id(), acc1_id, acc2_id, u1_name, u2_name, now, now),
        )

    conn.commit()


if __name__ == "__main__":
    init_db()
    print(f"Database ready at {DB_PATH}")
