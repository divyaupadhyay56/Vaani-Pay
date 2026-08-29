"""
Authentication & account management — now backed by the SQLite database
(app/db.py) instead of a static token list.

This module is the ONLY place that ever turns a client-supplied credential
(password, or a session token) into a trusted user identity. Everything
downstream (WebSocket chat, REST endpoints) uses the `user_id` this module
hands back — never a value taken from request bodies, URL parameters, or
chat text. That's what keeps user data isolated: see mcp_server/data_layer.py
for how every resource lookup re-checks ownership against this identity.

Flow:
    register()        -> creates a user row (password hashed, never stored raw)
    login()            -> verifies credentials, issues a new session token
    verify_token()     -> resolves a session token to a user identity (rejects
                          expired/unknown tokens)
    logout()           -> deletes a session token (server-side revocation)
    logout_all()       -> deletes every session token for a user (used by
                          "change password" and "delete account")
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app import db
from app.security import generate_token, hash_password, password_policy_error, verify_password

SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    """Raised for any user-facing auth/validation failure. `message` is safe to show the user."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class UserIdentity:
    user_id: str
    name: str
    email: str
    language: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_identity(row) -> UserIdentity:
    return UserIdentity(user_id=row["id"], name=row["name"], email=row["email"], language=row["language"])


# ---------------- Registration ----------------

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
        # Generic message on purpose — don't reveal which emails are registered.
        raise AuthError("Could not create account with the details provided.")

    user_id = f"user_{uuid.uuid4().hex[:12]}"
    now = _now()
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO users (id, name, email, phone, password_hash, language, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, name, email, phone, hash_password(password), language, now, now),
        )
        # Every user gets a payment account, created atomically with the user
        # row itself — a user can never exist without one (see app/wallet.py).
        from app import wallet  # local import: avoids a module-load cycle (wallet.py doesn't import auth)
        wallet.insert_account_row(conn, user_id)

    return UserIdentity(user_id=user_id, name=name, email=email, language=language)


# ---------------- Login / logout ----------------

def login(email: str, password: str) -> tuple[UserIdentity, str]:
    """Returns (identity, session_token). Raises AuthError on bad credentials."""
    email = (email or "").strip().lower()
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    # Same generic error whether the email doesn't exist or the password is
    # wrong — this avoids leaking which emails have accounts.
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
    """Resolves a session token to a verified user identity, or None if the
    token is missing, unknown, or expired. This is the single choke point
    every authenticated request (WebSocket and REST) goes through."""
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


# ---------------- Profile management ----------------

def get_profile(user_id: str) -> dict:
    conn = db.get_connection()
    row = conn.execute(
        "SELECT id, name, email, phone, language, created_at, updated_at, last_login FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        raise AuthError("User not found.", status_code=404)
    return dict(row)


def update_profile(user_id: str, name: str | None = None, phone: str | None = None) -> dict:
    fields, values = [], []
    if name is not None:
        name = name.strip()
        if not name or len(name) < 2:
            raise AuthError("Please enter a valid name.")
        fields.append("name = ?")
        values.append(name)
    if phone is not None:
        fields.append("phone = ?")
        values.append(phone.strip() or None)

    if not fields:
        return get_profile(user_id)

    fields.append("updated_at = ?")
    values.append(_now())
    values.append(user_id)

    with db.tx() as conn:
        conn.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
    return get_profile(user_id)


def update_language(user_id: str, language: str) -> dict:
    if language not in ("en", "hi"):
        raise AuthError("Unsupported language.")
    with db.tx() as conn:
        conn.execute("UPDATE users SET language = ?, updated_at = ? WHERE id = ?", (language, _now(), user_id))
    return get_profile(user_id)


def change_password(user_id: str, current_password: str, new_password: str) -> None:
    conn = db.get_connection()
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise AuthError("User not found.", status_code=404)
    if not verify_password(current_password or "", row["password_hash"]):
        raise AuthError("Current password is incorrect.", status_code=401)

    pw_error = password_policy_error(new_password)
    if pw_error:
        raise AuthError(pw_error)

    with db.tx() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (hash_password(new_password), _now(), user_id),
        )
    # Invalidate all existing sessions so a stolen/old token can't keep working.
    logout_all(user_id)


def delete_account(user_id: str, password: str) -> None:
    """Permanently deletes the user's account and all associated data.
    Requires re-authentication with the current password as a confirmation
    step, per the account-deletion requirement."""
    conn = db.get_connection()
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise AuthError("User not found.", status_code=404)
    if not verify_password(password or "", row["password_hash"]):
        raise AuthError("Password is incorrect.", status_code=401)

    with db.tx() as conn:
        # ON DELETE CASCADE handles sessions/chat_history/payments/orders/
        # refunds/transactions rows for this user.
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
