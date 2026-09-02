from __future__ import annotations

from datetime import datetime, timezone

from app import db
from app.core.exceptions import AuthError
from app.security import hash_password, password_policy_error, verify_password
from app.services.auth_service import logout_all


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    logout_all(user_id)


def delete_account(user_id: str, password: str) -> None:
    conn = db.get_connection()
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise AuthError("User not found.", status_code=404)
    if not verify_password(password or "", row["password_hash"]):
        raise AuthError("Password is incorrect.", status_code=401)

    with db.tx() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
