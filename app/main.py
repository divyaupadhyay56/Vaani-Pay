

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI

from app.config import settings
from app.error_handling import safe_error_message
from app.mcp_client import mcp_client
from app.routers import (
    auth_routes,
    beneficiary_routes,
    misc_routes,
    profile_routes,
    transaction_routes,
    wallet_routes,
    ws_routes,
)
from app import db

logger = logging.getLogger("vaani_pay")

app = FastAPI(title="Vaani Pay — Secure Payments Support Chatbot")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")

_allowed_origins = [o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins or ["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_routes.router)
app.include_router(profile_routes.router)
app.include_router(wallet_routes.router)
app.include_router(beneficiary_routes.router)
app.include_router(transaction_routes.router)
app.include_router(misc_routes.router)
app.include_router(ws_routes.router)


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
async def shutdown():
    await mcp_client.close()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": safe_error_message(exc)})