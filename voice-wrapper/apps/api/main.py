"""FastAPI application entry point."""
from fastapi import FastAPI
from apps.api.agents.agent_one_client import AgentOneClient
from apps.api.agents.registry import AgentRegistry
from apps.api.config import get_settings
from apps.api.realtime.openai_client import OpenAIRealtimeClient
from apps.api.routes.voice import router as voice_router
from apps.api.realtime.session_manager import SessionManager


app = FastAPI(title="Voice Wrapper API")
_settings = get_settings()
_registry = AgentRegistry()
_session_manager = SessionManager(
    realtime_client=OpenAIRealtimeClient(_settings),
    registry=_registry,
)
_agent_one_client = AgentOneClient(_settings)
app.state.session_manager = _session_manager
app.state.agent_registry = _registry
# Proxy so existing code that touches app.state.sessions still works
app.state.sessions = _session_manager._sessions
app.state.agent_invoke_fn = _agent_one_client.invoke
app.include_router(voice_router)
