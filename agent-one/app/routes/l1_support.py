from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Any

from app.l1_support.graph import build_l1_graph
from app.l1_support import db as _db

router = APIRouter()
_l1_graph = build_l1_graph()

_VALID_STATUSES = {"open", "in_progress", "resolved", "closed"}


class L1InvokeRequest(BaseModel):
    message: str
    thread_id: str
    user_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class UpdateStatusRequest(BaseModel):
    status: str


@router.post("/agents/l1-support/invoke")
def l1_invoke(request: L1InvokeRequest):
    config = {"configurable": {"thread_id": request.thread_id}}

    state = _l1_graph.invoke({
        "user_message": request.message,
        "thread_id": request.thread_id,
        "user_id": request.user_id or "guest",
    }, config=config)

    answer = state.get("final_answer", "")
    speak = state.get("speak") or answer
    return {
        "answer": answer,
        "speak": speak,
        "stage": state.get("stage", "greeting"),
        "ticket_id": state.get("ticket_id"),
        "existing_ticket_id": state.get("existing_ticket_id"),
        "company": state.get("company_name"),
        "application": state.get("application_name"),
        "employee_number": state.get("employee_number"),
        "escalation_team": state.get("escalation_team"),
        "escalation_contact": state.get("escalation_contact"),
        "escalation_sla_hours": state.get("escalation_sla_hours"),
        "requires_more_info": state.get("requires_more_info", True),
        "faq_matched": state.get("faq_matched", False),
        "email_sent": state.get("email_sent", False),
    }


@router.get("/agents/l1-support/tickets")
def list_tickets():
    return _db.all_tickets()


@router.get("/agents/l1-support/tickets/{ticket_id}")
def get_ticket(ticket_id: str):
    ticket = _db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@router.patch("/agents/l1-support/tickets/{ticket_id}/status")
def update_ticket_status(ticket_id: str, body: UpdateStatusRequest):
    if body.status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )
    ticket = _db.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    _db.update_ticket_status(ticket_id, body.status)
    return {"ok": True, "ticket_id": ticket_id, "status": body.status}
