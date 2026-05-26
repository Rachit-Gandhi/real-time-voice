"""FastAPI application entry point."""
from fastapi import FastAPI
from apps.api.routes.voice import router as voice_router


def _default_agent_invoke_fn(agent_id, user_message, session_id):
    raise NotImplementedError("agent_invoke_fn must be overridden before use")


app = FastAPI(title="Voice Wrapper API")
app.state.sessions = {}
app.state.agent_invoke_fn = _default_agent_invoke_fn
app.include_router(voice_router)
