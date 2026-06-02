"""FastAPI routes for the WWTS agent."""
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from wwts_agent.graph import build_wwts_graph

router = APIRouter(tags=["wwts-agent"])
_graph = build_wwts_graph()


class WWTSInvokeRequest(BaseModel):
    message: str
    thread_id: str
    user_id: str | None = None
    # context must contain:
    #   wwts_session: int   — session ID returned by /gtaccess/login
    #   customer_code: str  — customer code to scope WO queries
    context: dict[str, Any] = Field(default_factory=dict)


@router.post("/agents/wwts/invoke")
def wwts_invoke(request: WWTSInvokeRequest):
    config = {"configurable": {"thread_id": request.thread_id}}
    state = _graph.invoke(
        {
            "user_message": request.message,
            "thread_id": request.thread_id,
            "user_id": request.user_id or "",
            "context": request.context,
            # "messages" deliberately omitted — checkpoint preserves history
        },
        config=config,
    )
    return {
        "answer": state.get("final_answer", ""),
        "speak": state.get("speak") or state.get("final_answer", ""),
        "stage": state.get("stage", "greeting"),
        "intent": state.get("intent"),
        "wo_number": state.get("wo_number"),
        "wo_list": state.get("wo_list"),
        "created_wo_number": state.get("created_wo_number"),
        "requires_more_info": state.get("requires_more_info", True),
    }
