"""Unified server — single FastAPI app combining voice-wrapper and agent-one."""
import pathlib
import sys

_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "agent-one"))
sys.path.insert(0, str(_ROOT / "voice-wrapper"))

# Load root .env before any sub-package config is imported
from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=False)

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from apps.api.agents.registry import AgentRegistry
from apps.api.config import get_settings
from apps.api.realtime.openai_client import OpenAIRealtimeClient
from apps.api.realtime.session_manager import SessionManager
from apps.api.routes.voice import router as voice_router

from app.routes.agent_one import router as agent_one_router
from app.routes.l1_support import router as l1_support_router

from agents.invoker import DirectAgentInvoker
from auth import router as auth_router

_STATIC = _ROOT / "voice-wrapper" / "apps" / "api" / "static"

app = FastAPI(title="Real-Time Voice API")

_settings = get_settings()
_registry = AgentRegistry()
_session_manager = SessionManager(
    realtime_client=OpenAIRealtimeClient(_settings),
    registry=_registry,
)
_invoker = DirectAgentInvoker()

app.state.session_manager = _session_manager
app.state.agent_registry = _registry
app.state.sessions = _session_manager._sessions
app.state.agent_invoke_fn = _invoker.invoke

app.include_router(voice_router)
app.include_router(agent_one_router)
app.include_router(l1_support_router)
app.include_router(auth_router)
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/login", status_code=302)


@app.get("/login", include_in_schema=False)
def login_page():
    return FileResponse(str(_STATIC / "login.html"))


@app.get("/console", include_in_schema=False)
def console_page():
    return FileResponse(str(_STATIC / "index.html"))
