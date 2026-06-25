from typing import TypedDict


class L1SupportState(TypedDict, total=False):
    # Identity
    thread_id: str
    user_id: str
    user_message: str
    messages: list  # [{"role": "user"|"assistant", "content": str}]

    # Conversation stage
    # "greeting" → "troubleshooting" → "confirm_issue" → "identifying" → "filing" → "done"
    stage: str

    # Troubleshooting
    issue_summary: str
    steps_completed: list[str]   # e.g. ["internet_check", "cookies_clear"]
    issue_resolved: bool

    # Identification
    company_code: str | None     # SAMSUNG | PANASONIC | HAVELLS
    company_name: str | None
    application_id: str | None   # e.g. SAMSUNG-SVP
    application_name: str | None
    site_id: str | None
    contact_name: str | None
    contact_email: str | None
    employee_number: str | None  # employee ID used to look up / deduplicate tickets

    # Ticket
    ticket_id: str | None
    existing_ticket_id: str | None  # open ticket found for this employee
    email_sent: bool

    # Output
    final_answer: str
    speak: str
    requires_more_info: bool

    # Route handler fields
    faq_matched: bool
    escalation_team: str | None
    escalation_contact: str | None
    escalation_sla_hours: int | None
