"""Voice session routes."""
import uuid
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/voice", tags=["voice"])


class CreateSessionRequest(BaseModel):
    agent_id: str
    user_id: str


@router.post("/session")
def create_session(body: CreateSessionRequest):
    session_id = str(uuid.uuid4())
    return {
        "session_id": session_id,
        "agent_id": body.agent_id,
        "status": "active",
    }
