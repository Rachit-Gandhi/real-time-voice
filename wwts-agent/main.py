"""Standalone WWTS agent service — GTAccess login only."""
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "server"))

load_dotenv(_ROOT / ".env", override=False)

from auth import router as auth_router  # noqa: E402

_STATIC = _ROOT / "voice-wrapper" / "apps" / "api" / "static"

app = FastAPI(title="WWTS Agent")
app.include_router(auth_router)
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/")
def root():
    return FileResponse(str(_STATIC / "login.html"))
