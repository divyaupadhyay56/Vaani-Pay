from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse
from app.i18n import ui_strings

router = APIRouter(tags=["misc"])
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@router.get("/i18n/{lang}")
async def get_i18n(lang: str):
    return ui_strings(lang)


@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    favicon_path = PROJECT_ROOT / "static" / "favicon.svg"
    return FileResponse(favicon_path, media_type="image/svg+xml")


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
async def serve_ui():
    with open(PROJECT_ROOT / "static" / "index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read(), headers={"Cache-Control": "no-store, no-cache, must-revalidate"})