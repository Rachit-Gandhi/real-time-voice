"""FastAPI application entry point."""
import pathlib
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from apps.api.agents.agent_one_client import AgentOneClient
from apps.api.agents.registry import AgentRegistry
from apps.api.config import get_settings
from apps.api.realtime.openai_client import OpenAIRealtimeClient
from apps.api.routes.voice import router as voice_router
from apps.api.routes.transcripts import router as transcripts_router
from apps.api.realtime.session_manager import SessionManager
from apps.api.storage.transcript_store import TranscriptStore

_STATIC = pathlib.Path(__file__).parent / "static"

app = FastAPI(title="Voice Wrapper API")
_settings = get_settings()
_registry = AgentRegistry()
_session_manager = SessionManager(
    realtime_client=OpenAIRealtimeClient(_settings),
    registry=_registry,
)
_agent_one_client = AgentOneClient(_settings)
_transcript_store = TranscriptStore(_settings.transcript_db_path)
app.state.session_manager = _session_manager
app.state.agent_registry = _registry
app.state.transcript_store = _transcript_store
# Proxy so existing code that touches app.state.sessions still works
app.state.sessions = _session_manager._sessions
app.state.agent_invoke_fn = _agent_one_client.invoke
app.include_router(voice_router)
app.include_router(transcripts_router)
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(_STATIC / "index.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(_STATIC / "dashboard.html")
