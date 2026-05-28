from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Any

from app.l1_support.graph import build_l1_graph

router = APIRouter()
_l1_graph = build_l1_graph()


class L1InvokeRequest(BaseModel):
    message: str
    thread_id: str
    user_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


@router.post("/agents/l1-support/invoke")
def l1_invoke(request: L1InvokeRequest):
    config = {"configurable": {"thread_id": request.thread_id}}
    state = _l1_graph.invoke({
        "user_message": request.message,
        "thread_id": request.thread_id,
        "user_id": request.user_id or "guest",
    }, config=config)
    return {
        "answer": state.get("final_answer", ""),
        "speak": state.get("speak", ""),
        "stage": state.get("stage", "start"),
        "ticket_id": state.get("ticket_id"),
        "escalation_team": state.get("escalation_team"),
        "escalation_contact": state.get("escalation_contact"),
        "escalation_sla_hours": state.get("escalation_sla_hours"),
        "requires_more_info": state.get("requires_more_info", False),
        "faq_matched": state.get("faq_matched", False),
    }
