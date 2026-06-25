"""LLM-driven triage node — manages the full L1 conversation FSM."""
import json
import os
import re

from app.l1_support.state import L1SupportState
from app.l1_support import db as _db

_TROUBLESHOOT_STEPS = ["internet_check", "cookies_clear"]

_STEP_LABELS = {
    "internet_check": "checked their internet connection",
    "cookies_clear":  "cleared browser cookies and cache",
}

_AFFIRMATIVE = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "done", "did", "tried",
    "already", "cleared", "connected", "am", "have", "correct", "right", "affirmative",
    "confirm", "confirmed", "that's", "thats", "absolutely", "definitely",
}
_AFFIRMATIVE_PHRASES = [
    "i have", "i did", "i've", "i am", "i'm connected", "i cleared",
    "i tried", "yes i", "yeah i", "already done", "done that", "done both",
    "all of", "all the", "as well", "both", "that is correct", "that's correct",
    "sounds right", "yes that", "yeah that",
]

_SYSTEM = """You are an L1 support agent for enterprise software and hardware products.

Known companies and their applications:
{catalog}

Conversation stage: {stage}
Issue summary: {issue_summary}
Troubleshooting steps already confirmed by the user: {steps_done}
Identified — Company: {company} | Application: {application} | Contact: {contact_name} / Employee#: {employee_number}
Existing open ticket for this employee: {existing_ticket}

RULES BY STAGE:

GREETING
  Warmly greet the user. Ask what issue they are experiencing.
  Set new_stage="troubleshooting".

TROUBLESHOOTING
  Goal: confirm both steps below before moving on.
  Steps already confirmed are listed above — do NOT ask for them again.
  Step order:
    1. internet_check  — ask if they are connected to the internet
    2. cookies_clear   — ask if they cleared browser cookies/cache or tried incognito
  Ask only the NEXT un-confirmed step. One step per reply.
  If the user confirms both steps are done and the issue persists → set new_stage="confirm_issue".
  If the user says the issue is now resolved → set new_stage="done".

CONFIRM_ISSUE
  Summarize the issue in one sentence based on what the user described.
  Ask: "Just to confirm — [your summary of the issue]. Is that correct?"
  If user confirms → set new_stage="identifying".
  If user says no or gives a different description → update issue_summary and stay in confirm_issue.

IDENTIFYING
  You need: company (Samsung / Panasonic / Havells), application name, contact name, employee number.
  Ask for at most 2 missing pieces per reply.
  If the existing_ticket field above is not "none" it means this employee already has an open ticket —
  mention the existing ticket ID and ask if this is the same issue or a new one.
  When all four are collected → set new_stage="filing".
  IMPORTANT: only set application_id to a value that exists in the catalog above.
  If the user names an app that does not exist for their company, set application_id=null and
  ask them to confirm which listed application they mean.

DONE
  Thank the user. If a new ticket was filed include ticket ID {ticket_id}.
  If this was an existing ticket check, confirm the status.

Reply with ONLY valid JSON — no markdown, no extra text:
{{
  "response": "...",
  "speak": "...",
  "new_stage": "greeting|troubleshooting|confirm_issue|identifying|filing|done",
  "extracted": {{
    "issue_summary": "string or null",
    "step_completed": "internet_check|cookies_clear|null",
    "issue_resolved": false,
    "company_code": "SAMSUNG|PANASONIC|HAVELLS|null",
    "application_id": "<exact app_id from catalog or null>",
    "contact_name": "string or null",
    "employee_number": "string or null"
  }}
}}"""


# ── Deterministic helpers ──────────────────────────────────────────────────────

def _build_catalog() -> str:
    apps = _db.all_applications()
    by_company: dict[str, list[str]] = {}
    for a in apps:
        by_company.setdefault(a["company_name"], []).append(
            f"  - {a['name']} (id: {a['app_id']})"
        )
    lines = []
    for company, app_lines in by_company.items():
        lines.append(f"{company}:")
        lines.extend(app_lines)
    return "\n".join(lines)


def _is_affirmative(text: str) -> bool:
    lower = text.lower()
    if set(lower.split()) & _AFFIRMATIVE:
        return True
    return any(p in lower for p in _AFFIRMATIVE_PHRASES)


def _detect_confirmed_step(messages: list[dict], user_message: str, steps_done: list[str]) -> str | None:
    """
    Check what question the agent last asked, then see if the user's reply is
    affirmative. Returns the step key if confirmed, else None.
    This is the deterministic fallback when the LLM fails to extract step_completed.
    """
    if not _is_affirmative(user_message):
        return None

    last_agent = ""
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            last_agent = msg.get("content", "").lower()
            break

    if not last_agent:
        return None

    internet_kw = ["internet", "connected", "connection", "online", "network"]
    cookie_kw   = ["cookie", "cache", "clear", "incognito", "private window", "browser"]

    if any(k in last_agent for k in internet_kw) and "internet_check" not in steps_done:
        return "internet_check"
    if any(k in last_agent for k in cookie_kw) and "cookies_clear" not in steps_done:
        return "cookies_clear"
    return None


def _fuzzy_match_app(company_code: str, mention: str) -> dict | None:
    """Word-overlap match of a user's app mention against DB apps for the company."""
    if not mention or mention in ("null", "..."):
        return None
    apps = _db.apps_for_company(company_code)
    mention_words = [w for w in re.split(r"\W+", mention.lower()) if len(w) > 3]
    best, best_score = None, 0
    for app in apps:
        score = sum(1 for w in mention_words if w in app["name"].lower())
        if score > best_score:
            best_score, best = score, app
    return best if best_score > 0 else None


def _parse_llm_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


def _coerce_none(val) -> str | None:
    if val is None or str(val).strip() in ("null", "...", ""):
        return None
    return str(val).strip()


def _safe(s: str | None) -> str:
    """Escape curly braces so user text doesn't break str.format()."""
    return (s or "").replace("{", "{{").replace("}", "}}")


# ── Main node ─────────────────────────────────────────────────────────────────

def triage(state: L1SupportState) -> L1SupportState:
    stage            = state.get("stage") or "greeting"
    steps_done       = list(state.get("steps_completed") or [])
    issue_summary    = state.get("issue_summary") or ""
    company_code     = state.get("company_code")
    application_id   = state.get("application_id")
    contact_name     = state.get("contact_name")
    employee_number  = state.get("employee_number")
    ticket_id        = state.get("ticket_id") or ""
    existing_ticket_id = state.get("existing_ticket_id")

    messages     = list(state.get("messages") or [])
    user_message = state.get("user_message", "")
    if user_message:
        messages.append({"role": "user", "content": user_message})

    # ── Phase 1: deterministic step detection ─────────────────────────────────
    pre_detected_step = _detect_confirmed_step(messages[:-1], user_message, steps_done)
    if pre_detected_step and pre_detected_step not in steps_done:
        steps_done.append(pre_detected_step)

    # ── Phase 2: Python stage gates (pre-LLM) ─────────────────────────────────
    all_steps_done = all(s in steps_done for s in _TROUBLESHOOT_STEPS)

    if all_steps_done and stage == "troubleshooting":
        stage = "confirm_issue"

    # If user is confirming in confirm_issue stage, advance to identifying
    if stage == "confirm_issue" and _is_affirmative(user_message):
        stage = "identifying"

    steps_label = ", ".join(_STEP_LABELS[s] for s in steps_done) or "none yet"

    # ── Phase 3: call LLM ─────────────────────────────────────────────────────
    if not os.getenv("OPENAI_API_KEY"):
        return _fallback_response(state, stage, steps_done, messages)

    from langchain_openai import ChatOpenAI
    from app import config as cfg

    existing_label = (
        f"{existing_ticket_id} (open)" if existing_ticket_id else "none"
    )

    system_prompt = _SYSTEM.format(
        catalog=_build_catalog(),
        stage=stage.upper(),
        issue_summary=_safe(issue_summary or "not captured yet"),
        steps_done=steps_label,
        company=company_code or "unknown",
        application=application_id or "unknown",
        contact_name=_safe(contact_name or "unknown"),
        employee_number=_safe(employee_number or "unknown"),
        existing_ticket=existing_label,
        ticket_id=ticket_id or "pending",
    )

    llm = ChatOpenAI(model=cfg.OPENAI_MODEL, temperature=0.3)
    try:
        result = llm.invoke([{"role": "system", "content": system_prompt}] + messages)
        data = _parse_llm_json(result.content)
    except Exception:
        return _fallback_response(state, stage, steps_done, messages)

    response_text = data.get("response") or "I'm here to help. Could you describe the issue?"
    speak_text    = data.get("speak") or response_text
    new_stage     = data.get("new_stage") or stage
    extracted     = data.get("extracted") or {}

    # ── Phase 4: merge extracted fields ───────────────────────────────────────

    llm_step = _coerce_none(extracted.get("step_completed"))
    if llm_step and llm_step not in steps_done:
        steps_done.append(llm_step)

    new_issue_summary   = _coerce_none(extracted.get("issue_summary")) or issue_summary
    issue_resolved      = bool(extracted.get("issue_resolved"))

    new_company         = _coerce_none(extracted.get("company_code")) or company_code
    raw_app_id          = _coerce_none(extracted.get("application_id"))
    new_contact_name    = _coerce_none(extracted.get("contact_name"))   or contact_name
    new_employee_number = _coerce_none(extracted.get("employee_number")) or employee_number

    # ── Phase 5: validate & fix app match ─────────────────────────────────────
    new_app_id = raw_app_id or application_id

    if new_company and new_stage == "identifying":
        company_app_ids = {a["app_id"] for a in _db.apps_for_company(new_company)}

        if new_app_id and new_app_id not in company_app_ids:
            new_app_id = None

        if not new_app_id:
            fuzzy = _fuzzy_match_app(new_company, user_message)
            if not fuzzy:
                fuzzy = _fuzzy_match_app(new_company, new_issue_summary or "")

            if fuzzy:
                new_app_id = fuzzy["app_id"]
            else:
                apps = _db.apps_for_company(new_company)
                companies_map = {c["code"]: c["name"] for c in _db.all_companies()}
                cname = companies_map.get(new_company, new_company)
                app_list = " or ".join(f'"{a["name"]}"' for a in apps)
                response_text = (
                    f"I couldn't find that application for {cname}. "
                    f"Their registered applications are: {app_list}. "
                    f"Which one are you having trouble with?"
                )
                speak_text = response_text
                new_stage  = "identifying"

    # ── Phase 6: employee number lookup ───────────────────────────────────────
    new_existing_ticket_id = existing_ticket_id

    if new_employee_number and new_employee_number != employee_number:
        prior_tickets = _db.find_tickets_by_employee(new_employee_number)
        open_ones = [t for t in prior_tickets if t["status"] in ("open", "in_progress")]
        if open_ones:
            t = open_ones[0]
            new_existing_ticket_id = t["ticket_id"]
            status_label = t["status"].replace("_", " ")
            snippet = (t["issue_description"] or "")[:80]
            response_text = (
                f"I found an existing {status_label} ticket {t['ticket_id']} for employee {new_employee_number} "
                f"— the logged issue is: \"{snippet}\". "
                "Is this the same issue, or would you like to file a new ticket?"
            )
            speak_text = response_text
            new_stage = "identifying"

    # ── Phase 7: Python stage gates (post-LLM) ────────────────────────────────

    # Prevent LLM from prematurely jumping to filing
    if new_stage == "filing" and not (new_company and new_app_id and new_contact_name and new_employee_number):
        new_stage = "identifying"

    # Re-check all steps after LLM may have updated steps_done
    if all(s in steps_done for s in _TROUBLESHOOT_STEPS) and new_stage == "troubleshooting":
        new_stage = "confirm_issue"

    # identifying → filing when all four identifiers are present
    if new_stage == "identifying" and new_company and new_app_id and new_contact_name and new_employee_number:
        new_stage = "filing"

    # ── Resolve display names ─────────────────────────────────────────────────
    company_name     = state.get("company_name")
    application_name = state.get("application_name")

    if new_company and not company_name:
        companies_map = {c["code"]: c["name"] for c in _db.all_companies()}
        company_name  = companies_map.get(new_company)

    if new_app_id and not application_name:
        for a in _db.all_applications():
            if a["app_id"] == new_app_id:
                application_name = a["name"]
                break

    messages.append({"role": "assistant", "content": response_text})

    return {
        **state,
        "stage":              new_stage,
        "messages":           messages,
        "issue_summary":      new_issue_summary,
        "steps_completed":    steps_done,
        "issue_resolved":     issue_resolved,
        "company_code":       new_company,
        "company_name":       company_name,
        "application_id":     new_app_id,
        "application_name":   application_name,
        "contact_name":       new_contact_name,
        "employee_number":    new_employee_number,
        "existing_ticket_id": new_existing_ticket_id,
        "final_answer":       response_text,
        "speak":              speak_text,
        "requires_more_info": new_stage not in ("done", "filing"),
        "faq_matched":        False,
        "escalation_team":    None,
        "escalation_contact": None,
        "escalation_sla_hours": None,
    }


def _fallback_response(
    state: L1SupportState,
    stage: str,
    steps_done: list[str],
    messages: list[dict],
) -> L1SupportState:
    msgs = {
        "greeting":       "Hi! I'm here to help. What issue are you experiencing?",
        "troubleshooting": (
            "Are you currently connected to the internet?"
            if "internet_check" not in steps_done
            else "Have you tried clearing your browser cookies and cache?"
        ),
        "confirm_issue":  "Just to confirm the issue — could you briefly describe what's happening?",
        "identifying":    "Could I get your name and employee number to file a ticket?",
        "filing":         "I'm filing your ticket now.",
        "done":           "Your ticket has been submitted. Our support team will be in touch.",
    }
    msg = msgs.get(stage, "I'm here to help. Please describe your issue.")
    messages.append({"role": "assistant", "content": msg})
    return {
        **state,
        "stage":           stage,
        "steps_completed": steps_done,
        "messages":        messages,
        "final_answer":    msg,
        "speak":           msg,
        "requires_more_info": stage not in ("done", "filing"),
        "faq_matched":     False,
        "escalation_team": None,
        "escalation_contact": None,
        "escalation_sla_hours": None,
    }
