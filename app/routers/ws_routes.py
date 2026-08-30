from __future__ import annotations
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app import auth, db
from app.agent import handle_message
from app.error_handling import logger, safe_error_message
from app.nlu import understand
from app.session_store import append_history, clear_session, get_session, history_as_text, save_session
from app.websocket_manager import ws_manager

router = APIRouter(tags=["websocket"])

MAX_MESSAGE_LENGTH = 1000


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session_id = str(uuid.uuid4())
    await ws_manager.connect(session_id, websocket)
    session = get_session(session_id)

    async def emit(event_type: str, payload: dict):
        await ws_manager.send_event(session_id, event_type, payload)

    try:
        while not session.get("authenticated"):
            data = await websocket.receive_json()

            if not isinstance(data, dict) or data.get("type") != "auth":
                await emit("auth_error", {"error": "Please authenticate first."})
                continue

            token = data.get("token")
            if not isinstance(token, str) or not (0 < len(token) <= 500):
                await emit("auth_error", {"error": "Invalid token."})
                continue

            identity = auth.verify_token(token)
            if identity is None:
                await emit("auth_error", {"error": "Invalid or expired session. Please log in again."})
                continue

            session["authenticated"] = True
            session["user_id"] = identity.user_id
            session["user_name"] = identity.name
            session["language"] = identity.language
            session["simulation_mode"] = False  
            save_session(session_id, session)
            await emit("auth_success", {"user_id": identity.user_id, "name": identity.name, "language": identity.language})

        while True:
            data = await websocket.receive_json()

            if not isinstance(data, dict) or data.get("type") != "text":
                await emit("error", {"error": "Invalid message format."})
                continue

            text = data.get("text")
            if not isinstance(text, str) or not text.strip():
                await emit("error", {"error": "Message cannot be empty."})
                continue
            if len(text) > MAX_MESSAGE_LENGTH:
                await emit("error", {"error": f"Message too long (max {MAX_MESSAGE_LENGTH} characters)."})
                continue

            try:
                await emit("status", {"text": "🔍 Understanding your request..."})
                nlu = understand(text.strip(), conversation_context=history_as_text(session))
                append_history(session, "user", nlu.english_translation)
                _persist_chat_turn(session, session_id, "user", text.strip())

                async def ws_emit(event_type: str, payload: dict):
                    if event_type == "tool_start":
                        await emit("tool_start", {"text": f"🔧 {payload['label']}"})
                    elif event_type == "tool_result":
                        await emit("tool_result", {"text": f"✓ {payload['label']}"})
                    elif event_type in ("timeline", "preview", "risk"):
                        await emit(event_type, payload)

                reply = await handle_message(nlu, session, emit=ws_emit)

                await emit("status", {"text": "🤖 Generating response..."})
                append_history(session, "assistant", reply)
                _persist_chat_turn(session, session_id, "assistant", reply)
                save_session(session_id, session)

                await emit("message", {"text": reply})

            except Exception as e:
                await emit("error", {"error": safe_error_message(e)})

    except WebSocketDisconnect:
        ws_manager.disconnect(session_id)
        clear_session(session_id)


def _persist_chat_turn(session: dict, conversation_id: str, role: str, message: str) -> None:
    
    user_id = session.get("user_id")
    if not user_id:
        return
    try:
        with db.tx() as conn:
            conn.execute(
                "INSERT INTO chat_history (user_id, conversation_id, role, message, timestamp) VALUES (?, ?, ?, ?, ?)",
                (user_id, conversation_id, role, message, datetime.now(timezone.utc).isoformat()),
            )
    except Exception:
        logger.exception("Failed to persist chat history turn (non-fatal)")