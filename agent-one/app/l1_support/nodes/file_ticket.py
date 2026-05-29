"""Creates the work order in SQLite and fires the support email."""
from app.l1_support.state import L1SupportState
from app.l1_support import db as _db
from app.l1_support import emailer as _mail
from app.l1_support.work_order import build_work_order, persist_work_order


def file_ticket(state: L1SupportState) -> L1SupportState:
    company_code = state.get("company_code") or ""
    application_id = state.get("application_id") or ""

    # Look up company + application rows
    companies = {c["code"]: c for c in _db.all_companies()}
    company = companies.get(company_code)

    application = next(
        (a for a in _db.all_applications() if a["app_id"] == application_id),
        None,
    )

    if not company or not application:
        msg = (
            "I'm sorry — I couldn't match your company or application in our system. "
            "Could you double-check the name?"
        )
        return {
            **state,
            "stage": "identifying",
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    site = _db.find_site(company_code)

    wo = build_work_order(
        company_code=company_code,
        application=application,
        site=site,
        issue_description=state.get("issue_summary") or state.get("user_message", "No description"),
        contact_name=state.get("contact_name"),
        contact_email=state.get("contact_email"),
        employee_number=state.get("employee_number"),
    )

    ticket_id = persist_work_order(wo, company, application)

    # Email application support team
    email_sent = _mail.send_ticket_email(
        to=application["support_email"],
        ticket_id=ticket_id,
        company_name=company["name"],
        application_name=application["name"],
        issue_description=wo.open_remarks,
        contact_name=wo.contact_name,
        contact_email=wo.contact_email,
        site_id=wo.site_id,
    )

    if email_sent:
        _db.mark_email_sent(ticket_id)

    confirm = (
        f"Your support ticket has been created — ticket ID is {ticket_id}. "
        f"I've notified the {application['name']} support team at {company['name']}. "
        "You'll receive an email confirmation shortly."
    )
    speak = (
        f"Done! Your ticket {ticket_id} has been filed and the {application['name']} "
        f"support team has been notified. Check your email for confirmation."
    )

    messages = list(state.get("messages") or [])
    messages.append({"role": "assistant", "content": confirm})

    return {
        **state,
        "stage": "done",
        "ticket_id": ticket_id,
        "email_sent": email_sent,
        "final_answer": confirm,
        "speak": speak,
        "messages": messages,
        "requires_more_info": False,
        "faq_matched": False,
        "escalation_team": company["name"] + " Support",
        "escalation_contact": application["support_email"],
        "escalation_sla_hours": 4,
    }
