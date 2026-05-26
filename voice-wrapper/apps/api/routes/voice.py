"""Voice session routes."""
import uuid
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

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
