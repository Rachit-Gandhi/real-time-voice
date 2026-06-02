"""LLM-driven conversation node — manages the WWTS agent FSM."""
import json
import os
import re

from wwts_agent.state import WWTSState

_REQUIRED_CREATE = ["Product Reference", "Contact Name", "Contact Phone"]

_PURE_GREETINGS = {"hi", "hey", "hello", "howdy", "good morning", "good afternoon",
                   "good evening", "greetings", "sup", "yo"}


def _is_pure_greeting(text: str) -> bool:
    return text.strip().lower().rstrip("!.,") in _PURE_GREETINGS


def _missing_create_fields(fields: dict, has_customer_code: bool, multi_codes: bool = False) -> list[str]:
    fields = _normalize_create_fields(fields)
    missing = []
    if not fields.get("Customer Code"):
        if not has_customer_code or multi_codes:
            missing.append("Customer Code")
    for f in _REQUIRED_CREATE:
        if not fields.get(f):
            missing.append(f)
    has_site = bool(fields.get("Site ID"))
    has_location = bool(
        fields.get("Customer City")
        and fields.get("Customer State")
        and fields.get("Customer Postal Code")
    )
    if not has_site and not has_location:
        missing.append("Site ID or (Customer City + Customer State + Postal Code)")
    return missing


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


def _coerce_none(val) -> str | None:
    if val is None or str(val).strip() in ("null", "...", "", "None"):
        return None
    return str(val).strip()


def _safe(s: str | None) -> str:
    return (s or "").replace("{", "{{").replace("}", "}}")


def _normalize_create_fields(fields: dict) -> dict:
    """Normalize collected fields that voice extraction often combines."""
    normalized = dict(fields or {})
    for key, val in list(normalized.items()):
        if isinstance(val, str):
            normalized[key] = val.strip()

    city = normalized.get("Customer City")
    if isinstance(city, str) and not normalized.get("Customer State"):
        match = re.match(r"^\s*(?P<city>.+?),\s*(?P<state>[A-Za-z][A-Za-z .]{1,})\s*$", city)
        if match:
            normalized["Customer City"] = match.group("city").strip()
            normalized["Customer State"] = match.group("state").strip()

    return normalized


_CLOSED_KEYWORDS = {"closed", "completed", "finished", "resolved", "done", "complete"}
_OPEN_KEYWORDS   = {"open", "active", "in-progress", "in progress", "pending", "outstanding"}


def _detect_days_back(text: str) -> int | None:
    lower = text.lower()
    m = re.search(r'last\s+(\d+)\s+days?', lower)
    if m:
        return int(m.group(1))
    m = re.search(r'last\s+(\d+)\s+months?', lower)
    if m:
        return int(m.group(1)) * 30
    m = re.search(r'(\d+)\s+months?\s+back', lower)
    if m:
        return int(m.group(1)) * 30
    m = re.search(r'last\s+(\d+)\s+years?', lower)
    if m:
        return int(m.group(1)) * 365
    if any(k in lower for k in ("last year", "past year", "one year")):
        return 365
    if any(k in lower for k in ("six months", "6 months", "half year")):
        return 180
    if any(k in lower for k in ("beyond", "further back", "longer", "more history", "all time", "ever")):
        return 730
    return None


def _detect_wo_status(text: str) -> str | None:
    """Keyword-level status detection — used to override LLM extraction when it misses."""
    lower = text.lower()
    has_closed = any(k in lower for k in _CLOSED_KEYWORDS)
    has_open   = any(k in lower for k in _OPEN_KEYWORDS)
    has_all    = any(k in lower for k in ("all ", "any ", "every ", "all work", "all wo", "all status"))
    if has_all or (has_closed and has_open):
        return "A"
    if has_closed:
        return "C"
    if has_open:
        return "O"
    return None


_SYSTEM = """You are a WWTS work order assistant. Execute tasks immediately — do not ask for \
confirmation before listing or fetching work orders.

Current state:
- Stage: {stage}
- Prior intent: {intent}
- WO Number in context: {wo_number}
- WO status filter: {wo_status} (O=open, C=closed, A=all)
- Create WO fields so far: {create_fields}
- Missing required create fields: {missing_fields}
- Available customer codes ({num_codes}): {available_codes}

════════════════════════════════════════════
ROUTING RULES  (apply to EVERY stage)
════════════════════════════════════════════
Match the user message against these patterns and set new_stage IMMEDIATELY:

→ new_stage = "executing_list"  (no confirmation needed, just do it)
  Any question/request about: counts of WOs, open WOs, closed WOs, pending WOs,
  in-progress WOs, how many WOs, list WOs, show WOs, all work orders, current orders,
  do we have any, work orders for a customer, "list", "show", "how many", "any open",
  "closed", "completed", "finished", "what orders".
  Set extracted.wo_status = "O" for open (default), "C" for closed/completed/finished,
  "A" for all/any.

→ new_stage = "executing_get"  (set extracted.wo_number too)
  User provides a WO/order number explicitly, OR asks for details/status/history/updates
  of a specific order AND a WO number is already in context ({wo_number}).

→ new_stage = "collecting_wo_number"
  User asks for details/status of a WO but no WO number is known yet.

→ new_stage = "collecting_create"
  User wants to create / open / file a new work order.

If NONE of the above patterns match → stay in current stage and ask a clarifying question.

════════════════════════════════════════════
STAGE-SPECIFIC BEHAVIOUR
════════════════════════════════════════════

GREETING
  Apply routing rules first.
  Only if the message is a pure greeting with NO task content, respond warmly (1 sentence)
  and set new_stage = "intent".

INTENT
  Apply routing rules. Route immediately; do NOT ask for confirmation.

COLLECTING_WO_NUMBER
  Ask for the WO number. When user provides any number → extract it, executing_get.

COLLECTING_CREATE
  Ask for missing fields (at most 2 per reply). When all collected → executing_create.
  Missing: {missing_fields}
  PRIORITY: If "Customer Code" is in the missing list AND multiple codes are available,
  present the full list from "Available customer codes" and ask the user to choose ONE
  before asking for anything else. Extract the chosen code into extracted.create_fields.Customer Code.
  NOTE: City + State + Postal Code is sufficient for location — do NOT ask for a street address.
  NOTE: Only extract "Contact Name" when the user explicitly names the contact
  (e.g. "contact name is X", "the contact is X"). Do NOT extract it from possessive
  or qualifying phrases like "phone number for X" or "number for X".

DONE
  Previous task is complete. Acknowledge in ≤1 sentence.
  Then apply routing rules to the new message — route immediately if a task is present.
  If no new task → ask what else they need, set new_stage = "intent".

════════════════════════════════════════════
Reply ONLY with valid JSON — no markdown, no extra text:
{{
  "response": "...",
  "speak": "...",
  "new_stage": "intent|collecting_wo_number|collecting_create|executing_list|executing_get|executing_create|done",
  "extracted": {{
    "intent": "list_wo|get_wo|create_wo|null",
    "wo_number": "string or null",
    "wo_status": "O|C|A|null",
    "create_fields": {{
      "Customer Code": "string or null",
      "Product Reference": "string or null",
      "Contact Name": "string or null",
      "Contact Phone": "string or null",
      "Contact Email": "string or null",
      "Customer Address": "string or null",
      "Customer City": "string or null",
      "Customer Postal Code": "string or null",
      "Customer State": "string or null",
      "Site ID": "string or null",
      "Customer Call Number": "string or null"
    }}
  }}
}}"""


def converse(state: WWTSState) -> WWTSState:
    stage = state.get("stage") or "greeting"
    intent = state.get("intent")
    context = state.get("context") or {}
    customer_code = context.get("customer_code", "")
    customer_codes = context.get("customer_codes") or []
    wo_number = state.get("wo_number")
    create_fields = _normalize_create_fields(dict(state.get("create_fields") or {}))
    messages = list(state.get("messages") or [])
    user_message = state.get("user_message", "")

    if user_message:
        messages.append({"role": "user", "content": user_message})

    # Collapse "done" back to "greeting" only when message is a pure greeting
    if stage == "done" and user_message:
        stage = "intent"

    has_customer_code = bool(customer_code) or bool(customer_codes)
    multi_codes = len(customer_codes) > 1
    missing = _missing_create_fields(create_fields, has_customer_code, multi_codes)

    if not os.getenv("OPENAI_API_KEY"):
        return _fallback(state, stage, messages, user_message)

    from langchain_openai import ChatOpenAI

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # Build codes display for the prompt
    if customer_codes:
        codes_entries = [
            f"{c['code']} ({c['name']})" if isinstance(c, dict) else c
            for c in customer_codes
        ]
        available_codes = ", ".join(codes_entries)
        num_codes = len(customer_codes)
    else:
        available_codes = customer_code or "not provided"
        num_codes = 1 if customer_code else 0

    current_status = state.get("wo_status") or "O"
    system_prompt = _SYSTEM.format(
        stage=stage.upper(),
        intent=intent or "none",
        wo_number=_safe(wo_number or "none"),
        wo_status=_safe(current_status),
        create_fields=_safe(json.dumps(create_fields) if create_fields else "{}"),
        missing_fields=_safe(", ".join(missing) if missing else "none"),
        num_codes=num_codes,
        available_codes=_safe(available_codes),
    )

    llm = ChatOpenAI(model=model, temperature=0.1)
    try:
        result = llm.invoke(
            [{"role": "system", "content": system_prompt}] + messages
        )
        data = _parse_json(result.content)
    except Exception:
        return _fallback(state, stage, messages, user_message)

    response_text = data.get("response") or "How can I help you with work orders?"
    speak_text = data.get("speak") or response_text
    new_stage = data.get("new_stage") or stage
    extracted = data.get("extracted") or {}

    new_intent = _coerce_none(extracted.get("intent")) or intent
    new_wo_number = _coerce_none(extracted.get("wo_number")) or wo_number
    # Keyword detection overrides LLM extraction — catches cases where LLM returns null
    keyword_status = _detect_wo_status(user_message) if user_message else None
    new_wo_status = keyword_status or _coerce_none(extracted.get("wo_status")) or state.get("wo_status") or "O"
    keyword_days = _detect_days_back(user_message) if user_message else None
    new_days_back = keyword_days or state.get("wo_days_back")

    # Fields that must not be silently overwritten — only update if currently empty.
    # Prevents possessive phrases ("phone for Achyut") from clobbering explicit earlier values.
    _NO_OVERWRITE = {"Contact Name"}

    raw_create = extracted.get("create_fields") or {}
    for key, val in raw_create.items():
        coerced = _coerce_none(val)
        if coerced:
            if key in _NO_OVERWRITE and create_fields.get(key):
                continue  # already set — don't overwrite from incidental mention
            create_fields[key] = coerced
    create_fields = _normalize_create_fields(create_fields)

    # Auto-populate Customer Code only when the session has exactly one code
    if not create_fields.get("Customer Code"):
        if customer_code:
            create_fields["Customer Code"] = customer_code
        elif len(customer_codes) == 1:
            c = customer_codes[0]
            create_fields["Customer Code"] = c["code"] if isinstance(c, dict) else c
        # If multi_codes: leave empty — user must choose

    # Safety: block executing_create until all fields present
    if new_stage == "executing_create":
        if _missing_create_fields(create_fields, has_customer_code, multi_codes):
            new_stage = "collecting_create"

    messages.append({"role": "assistant", "content": response_text})

    return {
        **state,
        "stage": new_stage,
        "intent": new_intent,
        "wo_number": new_wo_number,
        "wo_status": new_wo_status,
        "wo_days_back": new_days_back,
        "create_fields": create_fields,
        "messages": messages,
        "final_answer": response_text,
        "speak": speak_text,
        "requires_more_info": new_stage not in (
            "executing_list", "executing_get", "executing_create", "done"
        ),
    }


_LIST_KW  = {"list", "show", "how many", "count", "open", "pending", "orders",
             "work orders", "any orders", "current", "in progress", "active"}
_GET_KW   = {"details", "status", "look up", "get wo", "history", "updates", "specific"}
_CREATE_KW = {"create", "open a", "new work order", "file", "submit"}


def _keyword_stage(text: str) -> str | None:
    lower = text.lower()
    if any(k in lower for k in _CREATE_KW):
        return "collecting_create"
    if any(k in lower for k in _GET_KW):
        return "collecting_wo_number"
    if any(k in lower for k in _LIST_KW):
        return "executing_list"
    return None


def _fallback(state: WWTSState, stage: str, messages: list, user_message: str = "") -> WWTSState:
    if _is_pure_greeting(user_message):
        msg = "Hello! I can list your work orders, look up a specific WO, or create a new one. What do you need?"
        new_stage = "intent"
    else:
        # Keyword-based routing so the agent progresses even without LLM
        routed = _keyword_stage(user_message) if user_message else None
        if routed:
            new_stage = routed
            msg = {
                "executing_list": "Let me check your open work orders.",
                "collecting_wo_number": "What work order number would you like to look up?",
                "collecting_create": "I can help create a work order. What is the product reference?",
            }.get(routed, "On it.")
        else:
            msgs_map = {
                "greeting": "I can list work orders, look up a WO, or create one. What would you like?",
                "intent": "Would you like to list work orders, get details on a specific one, or create a new one?",
                "collecting_wo_number": "What's the work order number you'd like to look up?",
                "collecting_create": "What's the product reference and contact name for the new work order?",
                "done": "Got it. Is there anything else I can help with?",
            }
            msg = msgs_map.get(stage, "How can I help with work orders?")
            new_stage = "intent" if stage in ("greeting", "done") else stage

    messages.append({"role": "assistant", "content": msg})
    return {
        **state,
        "stage": new_stage,
        "messages": messages,
        "final_answer": msg,
        "speak": msg,
        "requires_more_info": new_stage not in ("done",),
    }
