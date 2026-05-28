from typing import TypedDict


class L1SupportState(TypedDict, total=False):
    thread_id: str
    user_id: str
    user_message: str
    messages: list  # full conversation history as [{"role": "user"|"assistant", "content": str}]
    # FAQ stage
    faq_matched: bool
    faq_answer: str | None
    faq_category: str | None
    # Ticket collection stage
    stage: str  # "start" | "collecting" | "ticket_created"
    collected: dict  # {"name": ..., "email": ..., "issue": ...}
    missing_fields: list
    # Ticket
    ticket_id: str | None
    ticket_details: dict
    # Escalation
    escalation_team: str | None
    escalation_contact: str | None
    escalation_sla_hours: int | None
    # Output
    final_answer: str
    speak: str
    requires_more_info: bool
