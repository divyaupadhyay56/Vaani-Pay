"""
FastAPI entrypoint.

REST API (see README "API Design" for the full list):
    POST   /auth/register
    POST   /auth/login
    POST   /auth/logout
    GET    /users/me
    PUT    /users/me
    DELETE /users/me
    POST   /users/me/change-password
    GET    /users/me/preferences
    PUT    /users/me/preferences
    GET    /transactions
    GET    /transactions/{id}
    GET    /i18n/{lang}

WebSocket protocol (browser -> server), unchanged shape from the original
token-based design, but the token is now a DB-backed session token issued
by POST /auth/login instead of a static value:
    First message, required before anything else:
        {"type": "auth", "token": "..."}
    After successful auth, chat messages:
        {"type": "text", "text": "..."}

WebSocket protocol (server -> browser):
    {"type": "auth_success", "user_id": "...", "name": "...", "language": "en"}
    {"type": "auth_error", "error": "..."}
    {"type": "status",      "text": "..."}
    {"type": "tool_start",  "text": "..."}
    {"type": "tool_result", "text": "..."}
    {"type": "message",     "text": "<final answer, localized>"}
    {"type": "error",       "error": "..."}

SECURITY: no chat message is processed until the connection has
successfully authenticated. Once authenticated, every MCP tool call made
on behalf of this connection uses the resolved user_id from that
authentication step — never a value taken from the chat text itself. See
app/auth.py and app/agent.py for where this is enforced.
"""

import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from app import auth, db, wallet
from app.agent import handle_message
from app.config import settings
from app.i18n import ui_strings
from app.mcp_client import mcp_client
from app.nlu import understand
from app.session_store import append_history, clear_session, get_session, history_as_text, save_session
from app.websocket_manager import ws_manager
from mcp_server import data_layer

logger = logging.getLogger("vaani_pay")

app = FastAPI(title="Vaani Pay — Secure Payments Support Chatbot")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")

MAX_MESSAGE_LENGTH = 1000

# ---------------- CORS ----------------
# Secure by default: only same-origin/local dev origins unless explicitly
# overridden via CORS_ALLOWED_ORIGINS in .env (comma-separated).
_allowed_origins = [o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins or ["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


# ---------------- Simple in-memory rate limiting for auth endpoints ----------------
# A hackathon-scale limiter: N attempts per IP per rolling window. Good
# enough to blunt brute-force/credential-stuffing without adding a Redis
# dependency just for this; swap for a proper limiter behind a real
# deployment's load balancer/WAF.
_rate_limit_buckets: dict[str, list[float]] = {}
RATE_LIMIT_MAX_ATTEMPTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60


def _check_rate_limit(key: str):
    now = time.time()
    bucket = [t for t in _rate_limit_buckets.get(key, []) if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(bucket) >= RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")
    bucket.append(now)
    _rate_limit_buckets[key] = bucket


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ---------------- Auth dependency for REST endpoints ----------------

async def get_current_user(authorization: Optional[str] = Header(default=None)) -> auth.UserIdentity:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = authorization.split(" ", 1)[1].strip()
    identity = auth.verify_token(token)
    if identity is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    return identity


def _get_bearer_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    return authorization.split(" ", 1)[1].strip()


# ---------------- Request/response models ----------------

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    phone: Optional[str] = None
    language: str = "en"


class LoginRequest(BaseModel):
    email: str
    password: str


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None


class UpdatePreferencesRequest(BaseModel):
    language: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class DeleteAccountRequest(BaseModel):
    password: str
    confirm: bool = Field(..., description="Must be true to confirm permanent account deletion.")


# --- Wallet request models ---
#
# UPI PIN / payment-authentication-secret policy (applies to every model
# below): these schemas define the COMPLETE set of fields Vaani Pay will
# ever accept for Add Money or Send Money. There is no upi_pin, mpin, otp,
# card_pin, or transaction_password field — deliberately, permanently.
# `extra="forbid"` means a request containing ANY undeclared field (e.g. a
# client mistakenly or maliciously attaching a "upi_pin" key) is rejected
# outright with a 422 before wallet.py ever sees it — a UPI PIN literally
# cannot reach this codebase's application logic, database, or logs.
#
# If/when a real UPI-capable payment gateway (e.g. Razorpay Checkout) is
# wired into Add Money, PIN entry must happen entirely inside that
# gateway's own hosted checkout UI (redirect or embedded widget) — never
# by adding a PIN field to these models or any Vaani Pay-owned form. The
# gateway returns a payment/order result to verify; it must never hand a
# PIN to Vaani Pay to relay or store. See tests/test_no_payment_secrets.py
# for the regression tests enforcing this.

class AddMoneyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: float
    description: Optional[str] = None


class ValidateRecipientRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_name: str
    account_number: Optional[str] = None
    ifsc: Optional[str] = None


class InitiateTransferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_name: str
    account_number: str
    ifsc: str
    amount: float
    note: Optional[str] = None


class SaveBeneficiaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient_name: str
    account_number: str
    ifsc: str


# ---------------- Startup / shutdown ----------------

@app.on_event("startup")
async def startup():
    db.init_db()
    logger.info(f"Database ready at {db.DB_PATH}")

    if not settings.GROK_API_KEY:
        logger.warning(
            "\n=========================================================\n"
            "  WARNING: GROK_API_KEY is not set.\n"
            "  Every chat request will fail until you:\n"
            "    1. Get a key from https://console.x.ai\n"
            "    2. Add GROK_API_KEY=... to your .env file\n"
            "    3. Restart the server\n"
            "=========================================================\n"
        )
    else:
        try:
            client = OpenAI(api_key=settings.GROK_API_KEY, base_url=settings.GROK_BASE_URL)
            client.chat.completions.create(
                model=settings.GROK_MODEL,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            logger.info(f"Grok API reachable — model '{settings.GROK_MODEL}' responding.")
        except Exception as e:
            logger.warning(
                "\n=========================================================\n"
                f"  WARNING: Grok API test call failed: {e}\n"
                "  Check that GROK_API_KEY is valid and GROK_MODEL exists.\n"
                "=========================================================\n"
            )

    try:
        tools = await mcp_client.list_tools()
        logger.info(f"MCP server connected — {len(tools)} tools available: {[t['name'] for t in tools]}")
    except Exception as e:
        logger.exception("WARNING: Could not start/connect to the MCP server (%s: %r)", type(e).__name__, e)


@app.on_event("shutdown")
async def shutdown_mcp():
    await mcp_client.close()


def _safe_error_message(e: Exception) -> str:
    """
    Secure error handling: never echo raw exception text back to the client
    (it could contain internal details, file paths, or in a worse case,
    fragments of data). Log the real error server-side for debugging;
    return only a generic, safe message to the client.
    """
    logger.exception("Unhandled error")
    return "Something went wrong while processing your request. Please try again."


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": _safe_error_message(exc)})


# ---------------- Auth endpoints ----------------

@app.post("/auth/register")
async def register_endpoint(payload: RegisterRequest, request: Request):
    _check_rate_limit(f"register:{_client_key(request)}")
    try:
        identity = auth.register(
            name=payload.name, email=payload.email, password=payload.password,
            phone=payload.phone, language=payload.language,
        )
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    # A payment account is created atomically with the user row itself
    # (see app/auth.py's register() / app/wallet.py's insert_account_row) —
    # it always exists by the time we get here, never a separate step that
    # could fail independently.
    account = wallet.get_account(identity.user_id)
    return {
        "user_id": identity.user_id, "name": identity.name, "email": identity.email, "language": identity.language,
        "message": "Your payment account has been successfully created.",
        "account": account,
    }


@app.post("/auth/login")
async def login_endpoint(payload: LoginRequest, request: Request):
    _check_rate_limit(f"login:{_client_key(request)}")
    try:
        identity, token = auth.login(payload.email, payload.password)
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return {
        "token": token,
        "user": {"user_id": identity.user_id, "name": identity.name, "email": identity.email, "language": identity.language},
    }


@app.post("/auth/logout")
async def logout_endpoint(authorization: Optional[str] = Header(default=None)):
    token = _get_bearer_token(authorization)
    auth.logout(token)
    return {"status": "logged_out"}


# ---------------- Profile / account management ----------------

@app.get("/users/me")
async def get_me(user: auth.UserIdentity = Depends(get_current_user)):
    return auth.get_profile(user.user_id)


@app.put("/users/me")
async def update_me(payload: UpdateProfileRequest, user: auth.UserIdentity = Depends(get_current_user)):
    try:
        return auth.update_profile(user.user_id, name=payload.name, phone=payload.phone)
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@app.delete("/users/me")
async def delete_me(payload: DeleteAccountRequest, user: auth.UserIdentity = Depends(get_current_user)):
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Deletion must be explicitly confirmed.")
    try:
        auth.delete_account(user.user_id, payload.password)
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return {"status": "account_deleted"}


@app.post("/users/me/change-password")
async def change_password_endpoint(payload: ChangePasswordRequest, user: auth.UserIdentity = Depends(get_current_user)):
    try:
        auth.change_password(user.user_id, payload.current_password, payload.new_password)
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return {"status": "password_changed"}


@app.get("/users/me/preferences")
async def get_preferences(user: auth.UserIdentity = Depends(get_current_user)):
    profile = auth.get_profile(user.user_id)
    return {"language": profile["language"]}


@app.put("/users/me/preferences")
async def update_preferences(payload: UpdatePreferencesRequest, user: auth.UserIdentity = Depends(get_current_user)):
    try:
        profile = auth.update_language(user.user_id, payload.language)
    except auth.AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return {"language": profile["language"]}


# ---------------- Transactions (REST) ----------------
# The AI/WebSocket path is the primary UX, but plain REST access is offered
# too (per the API design requirements) — both go through the exact same
# ownership-checked data layer as the MCP tools.

@app.get("/transactions")
async def list_transactions(user: auth.UserIdentity = Depends(get_current_user)):
    return data_layer.get_transaction_history(user.user_id)


@app.get("/transactions/{txn_id}")
async def get_transaction(txn_id: str, user: auth.UserIdentity = Depends(get_current_user)):
    history = data_layer.get_transaction_history(user.user_id)["transactions"]
    for txn in history:
        if txn["txn_id"] == txn_id:
            return txn
    # Same generic response used everywhere else for "not found or not yours".
    raise HTTPException(status_code=404, detail="Transaction not found.")


# ---------------- Wallet (real money-movement system) ----------------
# Every endpoint below resolves the acting account from the AUTHENTICATED
# user (`user.user_id`, from the verified session token) — never from any
# account/user id in the request body or URL. See app/wallet.py's module
# docstring for the full ownership-enforcement design; these endpoints are
# thin wrappers with no additional logic of their own, so there is no
# separate code path here that could enforce weaker rules than the AI/MCP
# tools do.

def _wallet_error_to_http(e: "wallet.WalletError") -> HTTPException:
    status = e.status_code
    if e.code == "insufficient_balance":
        status = 402  # Payment Required — distinct, useful status for the frontend to branch on
    return HTTPException(status_code=status, detail=e.message)


@app.get("/wallet/account")
async def get_wallet_account(user: auth.UserIdentity = Depends(get_current_user)):
    try:
        return wallet.get_account(user.user_id)
    except wallet.WalletError as e:
        raise _wallet_error_to_http(e)


@app.post("/wallet/add-money")
async def add_money_endpoint(payload: AddMoneyRequest, user: auth.UserIdentity = Depends(get_current_user)):
    try:
        return wallet.add_money(user.user_id, payload.amount, payload.description)
    except wallet.WalletError as e:
        raise _wallet_error_to_http(e)


@app.post("/wallet/validate-recipient")
async def validate_recipient_endpoint(payload: ValidateRecipientRequest, user: auth.UserIdentity = Depends(get_current_user)):
    return wallet.validate_recipient(user.user_id, payload.recipient_name, payload.account_number, payload.ifsc)


@app.post("/wallet/transfers")
@app.post("/wallet/transfer/initiate")
async def initiate_transfer_endpoint(payload: InitiateTransferRequest, user: auth.UserIdentity = Depends(get_current_user)):
    """Step 1 of Send Money: validates everything and creates a PENDING
    transaction. Does NOT move any money — the frontend shows this as the
    confirmation screen, then calls /wallet/transfers/{id}/confirm."""
    try:
        return wallet.initiate_transfer(
            user.user_id, payload.recipient_name, payload.account_number, payload.ifsc, payload.amount, payload.note,
        )
    except wallet.WalletError as e:
        raise _wallet_error_to_http(e)


@app.post("/wallet/transfers/{transaction_id}/confirm")
@app.post("/wallet/transfer/{transaction_id}/confirm")
async def confirm_transfer_endpoint(transaction_id: str, user: auth.UserIdentity = Depends(get_current_user)):
    """Step 2 of Send Money: actually moves the money, atomically. Only
    succeeds if the PENDING transaction was initiated by this same
    authenticated user as the sender — re-validated here, not just trusted
    from the URL."""
    try:
        return wallet.confirm_transfer(user.user_id, transaction_id)
    except wallet.WalletError as e:
        raise _wallet_error_to_http(e)


@app.post("/wallet/transfers/{transaction_id}/cancel")
@app.post("/wallet/transfer/{transaction_id}/cancel")
async def cancel_transfer_endpoint(transaction_id: str, user: auth.UserIdentity = Depends(get_current_user)):
    try:
        return wallet.cancel_transfer(user.user_id, transaction_id)
    except wallet.WalletError as e:
        raise _wallet_error_to_http(e)


@app.get("/wallet/transactions")
async def wallet_transactions_endpoint(filter: str = "all", user: auth.UserIdentity = Depends(get_current_user)):
    try:
        return wallet.get_wallet_transactions(user.user_id, filter)
    except wallet.WalletError as e:
        raise _wallet_error_to_http(e)


@app.get("/wallet/spending-summary")
async def spending_summary_endpoint(period: str = "month", user: auth.UserIdentity = Depends(get_current_user)):
    try:
        return wallet.get_spending_summary(user.user_id, period)
    except wallet.WalletError as e:
        raise _wallet_error_to_http(e)


# ---------------- Beneficiaries ----------------

@app.get("/beneficiaries")
@app.get("/wallet/beneficiaries")
async def list_beneficiaries_endpoint(user: auth.UserIdentity = Depends(get_current_user)):
    return {"beneficiaries": wallet.list_beneficiaries(user.user_id)}


@app.post("/beneficiaries")
@app.post("/wallet/beneficiaries")
async def save_beneficiary_endpoint(payload: SaveBeneficiaryRequest, user: auth.UserIdentity = Depends(get_current_user)):
    try:
        return wallet.save_beneficiary(user.user_id, payload.recipient_name, payload.account_number, payload.ifsc)
    except wallet.WalletError as e:
        raise _wallet_error_to_http(e)


@app.delete("/beneficiaries/{beneficiary_id}")
async def delete_beneficiary_endpoint(beneficiary_id: int, user: auth.UserIdentity = Depends(get_current_user)):
    try:
        wallet.delete_beneficiary(user.user_id, beneficiary_id)
    except wallet.WalletError as e:
        raise _wallet_error_to_http(e)
    return {"status": "deleted"}


# ---------------- i18n ----------------

@app.get("/i18n/{lang}")
async def get_i18n(lang: str):
    return ui_strings(lang)


# ---------------- WebSocket chat ----------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    session_id = str(uuid.uuid4())
    await ws_manager.connect(session_id, websocket)
    session = get_session(session_id)

    async def emit(event_type: str, payload: dict):
        await ws_manager.send_event(session_id, event_type, payload)

    try:
        # --- Authentication gate: nothing else is processed until this succeeds ---
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

            session["authenticated"]  = True
            session["user_id"]        = identity.user_id
            session["user_name"]      = identity.name
            session["language"]       = identity.language
            session["simulation_mode"] = False   # toggled via chat command
            save_session(session_id, session)
            await emit("auth_success", {"user_id": identity.user_id, "name": identity.name, "language": identity.language})

        # --- Authenticated chat loop ---
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
                        # Forward agentic events to the browser UI
                        await emit(event_type, payload)

                reply = await handle_message(nlu, session, emit=ws_emit)

                await emit("status", {"text": "🤖 Generating response..."})
                append_history(session, "assistant", reply)
                _persist_chat_turn(session, session_id, "assistant", reply)
                save_session(session_id, session)

                await emit("message", {"text": reply})

            except Exception as e:
                await emit("error", {"error": _safe_error_message(e)})

    except WebSocketDisconnect:
        ws_manager.disconnect(session_id)
        clear_session(session_id)


def _persist_chat_turn(session: dict, conversation_id: str, role: str, message: str) -> None:
    """Best-effort persistence of chat turns to the chat_history table.
    Never allowed to break the live chat flow if it fails."""
    user_id = session.get("user_id")
    if not user_id:
        return
    try:
        from datetime import datetime, timezone
        with db.tx() as conn:
            conn.execute(
                "INSERT INTO chat_history (user_id, conversation_id, role, message, timestamp) VALUES (?, ?, ?, ?, ?)",
                (user_id, conversation_id, role, message, datetime.now(timezone.utc).isoformat()),
            )
    except Exception:
        logger.exception("Failed to persist chat history turn (non-fatal)")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    favicon_path = PROJECT_ROOT / "static" / "favicon.svg"
    return FileResponse(favicon_path, media_type="image/svg+xml")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    with open(PROJECT_ROOT / "static" / "index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read(), headers={"Cache-Control": "no-store, no-cache, must-revalidate"})
