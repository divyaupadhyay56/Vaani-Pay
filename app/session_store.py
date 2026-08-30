
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
        "user_id": None,      
        "user_name": None,
        "language": "en",        
        "pending_action": None, 
        "pending_payload": {},
        "history": [],          
    }


def append_history(session: dict[str, Any], role: str, text: str, max_turns: int = 6) -> None:
    session["history"].append({"role": role, "text": text})
    session["history"] = session["history"][-max_turns:]


def history_as_text(session: dict[str, Any]) -> str:
    return "\n".join(f"{h['role']}: {h['text']}" for h in session["history"])
