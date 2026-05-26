"""Voice session routes."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from apps.api.realtime.tool_router import ToolRouter

router = APIRouter(prefix="/voice", tags=["voice"])


class CreateSessionRequest(BaseModel):
    agent_id: str
    user_id: str


@router.post("/session")
def create_session(body: CreateSessionRequest, request: Request):
    session = request.app.state.session_manager.create(
        agent_id=body.agent_id,
        user_id=body.user_id,
    )
    return session


@router.get("/session/{session_id}/status")
def get_session_status(session_id: str, request: Request):
    try:
        return request.app.state.session_manager.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


@router.post("/session/{session_id}/end")
def end_session(session_id: str, request: Request):
    try:
        return request.app.state.session_manager.end(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


class ToolCallRequest(BaseModel):
    tool_name: str
    args: dict


@router.post("/session/{session_id}/tool-call")
def tool_call(session_id: str, body: ToolCallRequest, request: Request):
    try:
        request.app.state.session_manager.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    agent_invoke_fn = request.app.state.agent_invoke_fn
    router_instance = ToolRouter(agent_invoke_fn=agent_invoke_fn)
    try:
        result = router_instance.dispatch(tool_name=body.tool_name, args=body.args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result
