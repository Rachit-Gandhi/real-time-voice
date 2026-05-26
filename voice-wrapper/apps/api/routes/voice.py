"""Voice session routes."""
import uuid
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from apps.api.realtime.tool_router import ToolRouter

router = APIRouter(prefix="/voice", tags=["voice"])


class CreateSessionRequest(BaseModel):
    agent_id: str
    user_id: str


@router.post("/session")
def create_session(body: CreateSessionRequest, request: Request):
    session_id = str(uuid.uuid4())
    request.app.state.sessions[session_id] = {
        "session_id": session_id,
        "agent_id": body.agent_id,
        "status": "active",
    }
    return request.app.state.sessions[session_id]


@router.post("/session/{session_id}/end")
def end_session(session_id: str, request: Request):
    sessions = request.app.state.sessions
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    sessions[session_id]["status"] = "ended"
    return {"session_id": session_id, "status": "ended"}


class ToolCallRequest(BaseModel):
    tool_name: str
    args: dict


@router.post("/session/{session_id}/tool-call")
def tool_call(session_id: str, body: ToolCallRequest, request: Request):
    sessions = request.app.state.sessions
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    agent_invoke_fn = request.app.state.agent_invoke_fn
    router_instance = ToolRouter(agent_invoke_fn=agent_invoke_fn)
    try:
        result = router_instance.dispatch(tool_name=body.tool_name, args=body.args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result
