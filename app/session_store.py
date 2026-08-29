"""
Per-connection conversation + authentication state, keyed by a session id
(the WebSocket connection id in this app).

Defaults to a simple in-memory dict, which is fine for a single-process
deployment. Set USE_REDIS=true in .env to persist across restarts / workers.

SECURITY NOTE: `user_id` here is set exactly once, at authentication time
(app/auth.py, via app/main.py's WebSocket auth step), and is the ONLY
identity ever passed into MCP tool calls as requesting_user_id. Nothing in
this file, and nothing later in the pipeline, ever overwrites user_id from
a chat message or LLM-extracted value.
"""

import json
from typing import Any

from app.config import settings

_memory_store: dict[str, dict[str, Any]] = {}

_redis_client = None
if settings.USE_REDIS:
    import redis

    _redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)


def get_session(session_id: str) -> dict[str, Any]:
    if _redis_client:
        raw = _redis_client.get(f"session:{session_id}")
        return json.loads(raw) if raw else _default_session()
    return _memory_store.get(session_id, _default_session())


def save_session(session_id: str, session: dict[str, Any]) -> None:
    if _redis_client:
        _redis_client.set(f"session:{session_id}", json.dumps(session), ex=3600)
    else:
        _memory_store[session_id] = session


def clear_session(session_id: str) -> None:
    if _redis_client:
        _redis_client.delete(f"session:{session_id}")
    else:
        _memory_store.pop(session_id, None)


def _default_session() -> dict[str, Any]:
    return {
        "authenticated": False,
        "user_id": None,       # set only via a verified token — see app/auth.py
        "user_name": None,
        "language": "en",        # the authenticated user's persisted language preference (app/db.py)
        "pending_action": None,  # e.g. "awaiting_payment_id" — for "please enter your payment ID" follow-ups
        "pending_payload": {},
        "history": [],           # list of {"role": ..., "text": ...}
    }


def append_history(session: dict[str, Any], role: str, text: str, max_turns: int = 6) -> None:
    session["history"].append({"role": role, "text": text})
    session["history"] = session["history"][-max_turns:]


def history_as_text(session: dict[str, Any]) -> str:
    return "\n".join(f"{h['role']}: {h['text']}" for h in session["history"])
