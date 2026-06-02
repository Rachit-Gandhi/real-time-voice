"""Standalone WWTS agent service."""
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_ROOT = Path(__file__).resolve().parent.parent
_HERE = Path(__file__).resolve().parent

# Make server/ importable (auth, portals env helpers)
sys.path.insert(0, str(_ROOT / "server"))
# Make wwts-agent/ importable (wwts_agent package, routes)
sys.path.insert(0, str(_HERE))

load_dotenv(_ROOT / ".env", override=False)

from auth import router as auth_router  # noqa: E402
from routes.wwts_agent import router as wwts_router  # noqa: E402

_STATIC = _ROOT / "voice-wrapper" / "apps" / "api" / "static"

app = FastAPI(title="WWTS Agent")
app.include_router(auth_router)
app.include_router(wwts_router)
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/")
def root():
    return FileResponse(str(_STATIC / "login.html"))
