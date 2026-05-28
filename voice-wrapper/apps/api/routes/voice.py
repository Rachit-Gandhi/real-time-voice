"""Voice session routes."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from apps.api.agents.agent_one_client import AgentInvokeError
from apps.api.realtime.openai_client import RealtimeSessionError
from apps.api.realtime.tool_router import ToolRouter

router = APIRouter(prefix="/voice", tags=["voice"])


class CreateSessionRequest(BaseModel):
    agent_id: str
    user_id: str


@router.post("/session")
async def create_session(body: CreateSessionRequest, request: Request):
    try:
        session = await request.app.state.session_manager.create(
            agent_id=body.agent_id,
            user_id=body.user_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RealtimeSessionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return session


@router.get("/sessions")
def list_sessions(request: Request):
    return list(request.app.state.session_manager._sessions.values())


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
async def tool_call(session_id: str, body: ToolCallRequest, request: Request):
    try:
        session = request.app.state.session_manager.get(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    agent_invoke_fn = request.app.state.agent_invoke_fn
    router_instance = ToolRouter(agent_invoke_fn=agent_invoke_fn)
    args = {
        "agent_id": body.args.get("agent_id") or session["agent_id"],
        "user_message": body.args.get("user_message") or body.args.get("message"),
        "session_id": body.args.get("session_id") or session_id,
        "user_id": body.args.get("user_id") or session["user_id"],
        "context": body.args.get("context"),
    }
    try:
        result = await router_instance.dispatch(tool_name=body.tool_name, args=args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AgentInvokeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    user_msg = args.get("user_message") or ""
    agent_reply = result.get("speak") or result.get("answer") or ""
    request.app.state.session_manager.add_turn(session_id, user_msg, agent_reply)

    return result
