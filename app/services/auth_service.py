from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone

from app import db
from app.core.exceptions import AuthError
from app.core.types import UserIdentity
from app.security import generate_token, hash_password, password_policy_error, verify_password

SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_identity(row) -> UserIdentity:
    return UserIdentity(user_id=row["id"], name=row["name"], email=row["email"], language=row["language"])


def register(name: str, email: str, password: str, phone: str | None = None, language: str = "en") -> UserIdentity:
    name = (name or "").strip()
    email = (email or "").strip().lower()
    phone = (phone or "").strip() or None
    language = language if language in ("en", "hi") else "en"

    if not name or len(name) < 2:
        raise AuthError("Please enter your full name.")
    if not _EMAIL_RE.match(email):
        raise AuthError("Please enter a valid email address.")
    pw_error = password_policy_error(password)
    if pw_error:
        raise AuthError(pw_error)

    conn = db.get_connection()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing is not None:
        raise AuthError("Could not create account with the details provided.")

    user_id = f"user_{uuid.uuid4().hex[:12]}"
    now = _now()
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO users (id, name, email, phone, password_hash, language, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, email, phone, hash_password(password), language, now, now),
        )
        from app import wallet
        wallet.insert_account_row(conn, user_id)

    return UserIdentity(user_id=user_id, name=name, email=email, language=language)


def login(email: str, password: str) -> tuple[UserIdentity, str]:
    """Returns (identity, session_token). Raises AuthError on bad credentials."""
    email = (email or "").strip().lower()
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    if row is None or not verify_password(password or "", row["password_hash"]):
        raise AuthError("Invalid email or password.", status_code=401)

    token = generate_token()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=SESSION_TTL_HOURS)
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, row["id"], now.isoformat(), expires.isoformat()),
        )
        conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (now.isoformat(), row["id"]))

    return _row_to_identity(row), token


def verify_token(token: str) -> UserIdentity | None:
    if not token or not isinstance(token, str):
        return None
    token = token.strip()
    if not token:
        return None

    conn = db.get_connection()
    row = conn.execute(
        "SELECT s.expires_at, u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
        (token,),
    ).fetchone()
    if row is None:
        return None

    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        with db.tx() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        return None

    return _row_to_identity(row)


def logout(token: str) -> None:
    with db.tx() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def logout_all(user_id: str) -> None:
    with db.tx() as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
