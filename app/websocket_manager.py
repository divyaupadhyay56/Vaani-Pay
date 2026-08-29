"""
WebSocket Manager — the browser<->backend real-time channel.

Tracks active connections by server-generated session id and provides a
small helper to stream typed JSON events to the browser:
{"type": "auth_success"/"auth_error", ...}, {"type": "status", ...},
{"type": "tool_start"/"tool_result", ...}, {"type": "message", ...},
{"type": "error", ...} — this is what drives the live status stream in the UI.
"""

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self.active: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active[session_id] = websocket

    def disconnect(self, session_id: str):
        self.active.pop(session_id, None)

    async def send_event(self, session_id: str, event_type: str, payload: dict):
        ws = self.active.get(session_id)
        if ws is None:
            return
        await ws.send_json({"type": event_type, **payload})


ws_manager = WebSocketManager()
