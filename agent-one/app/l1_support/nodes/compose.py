from app.l1_support.state import L1SupportState

_FIELD_QUESTIONS = {
    "name": "Could you please provide your full name?",
    "email": "What email address should we use to reach you?",
    "issue": "Could you describe your issue in a bit more detail so I can help you better?",
}


def compose_answer(state: L1SupportState) -> L1SupportState:
    # Case 1: FAQ matched
    if state.get("faq_matched") and state.get("faq_answer"):
        answer = f"Here's the answer from our FAQ: {state['faq_answer']}"
        speak = answer
        return {
            **state,
            "final_answer": answer,
            "speak": speak,
        }

    # Case 2: More info required — ask for the first missing field
    if state.get("requires_more_info") and state.get("missing_fields"):
        first_missing = state["missing_fields"][0]
        question = _FIELD_QUESTIONS.get(
            first_missing,
            f"Could you please provide your {first_missing}?"
        )
        return {
            **state,
            "final_answer": question,
            "speak": question,
        }

    # Case 3: Ticket created — confirmation with ticket ID and escalation
    if state.get("stage") == "ticket_created":
        ticket_id = state.get("ticket_id", "N/A")
        team = state.get("escalation_team", "our support team")
        contact = state.get("escalation_contact", "support@company.com")
        sla = state.get("escalation_sla_hours")

        sla_text = f" They aim to respond within {sla} hour{'s' if sla != 1 else ''}." if sla else ""
        answer = (
            f"Your support ticket has been created successfully. "
            f"Your ticket ID is {ticket_id}. "
            f"Your issue has been assigned to {team} ({contact}).{sla_text} "
            f"You'll receive a confirmation at the email you provided."
        )
        speak = (
            f"Done! Your ticket {ticket_id} has been created and assigned to {team}.{sla_text} "
            f"Check your email for confirmation."
        )
        return {
            **state,
            "final_answer": answer,
            "speak": speak,
        }

    # Fallback
    fallback_msg = "I'm here to help. Could you tell me more about what you need assistance with?"
    return {
        **state,
        "final_answer": fallback_msg,
        "speak": fallback_msg,
    }
