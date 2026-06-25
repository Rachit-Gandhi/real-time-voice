import time
from datetime import datetime, timezone

from app.l1_support.state import L1SupportState


def create_ticket(state: L1SupportState) -> L1SupportState:
    collected = state.get("collected") or {}
    ticket_id = f"TKT-{int(time.time())}"
    ticket = {
        "ticket_id": ticket_id,
        "user_name": collected.get("name"),
        "user_email": collected.get("email"),
        "issue": collected.get("issue"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "open",
        "user_id": state.get("user_id"),
        "thread_id": state.get("thread_id"),
    }

    return {
        **state,
        "ticket_id": ticket_id,
        "ticket_details": ticket,
        "stage": "ticket_created",
    }
