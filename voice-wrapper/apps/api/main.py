"""FastAPI application entry point."""
from fastapi import FastAPI
from apps.api.routes.voice import router as voice_router
from apps.api.realtime.session_manager import SessionManager


def _default_agent_invoke_fn(agent_id, user_message, session_id):
    raise NotImplementedError("agent_invoke_fn must be overridden before use")


app = FastAPI(title="Voice Wrapper API")
_session_manager = SessionManager()
app.state.session_manager = _session_manager
# Proxy so existing code that touches app.state.sessions still works
app.state.sessions = _session_manager._sessions
app.state.agent_invoke_fn = _default_agent_invoke_fn
app.include_router(voice_router)
