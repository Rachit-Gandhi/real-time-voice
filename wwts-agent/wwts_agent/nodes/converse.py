"""LLM-driven conversation node — manages the WWTS agent FSM."""
import datetime
import json
import os
import re

from wwts_agent import api
from wwts_agent import faq
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


_SESSION_EXPIRED_MSG = (
    "Your WWTS session has expired. Please log out and log back in, then try again."
)


def _friendly_err(err: str | None) -> str:
    """Translate a raw WWTS error into a user-facing message (re-login on expiry)."""
    if api.is_session_expired_error(err):
        return _SESSION_EXPIRED_MSG
    return err or ""


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

    api._split_city_state_zip(normalized)
    return normalized


_CLOSED_KEYWORDS = {"closed", "completed", "finished", "resolved", "done", "complete"}
_OPEN_KEYWORDS   = {"open", "active", "in-progress", "in progress", "pending", "outstanding"}
_PARTS_KEYWORDS  = {"part", "parts", "shipped", "spare", "component"}
_LABOR_KEYWORDS  = {"labor", "technician", "tech ", "engineer", "csr", "assigned to"}
_SITE_FOCUS_KEYWORDS = {"site address", "site detail", "site for", "site location", "site info"}
_PART_LINE_KEYWORDS = {"part line", "line detail", "part detail"}
_LABOR_ACT_KEYWORDS = {"labor activit", "lbr act", "activities on", "labor history"}
_SEARCH_KW = {
    "find order", "find work", "search for", "search wo", "look for order",
    "lookup order", "customer call", "call number", "cust call", "serial number",
    "site id", "orders with model", "orders for model", "find wo",
}
_LIST_SIMPLE_KW = {
    "how many", "list my", "list open", "show open", "show my open",
    "show all", "all open work", "count open", "any open work",
}

_FOCUS_STAGE_BY_INTENT = {
    "get_wo_parts": "executing_get_parts",
    "get_wo_labor": "executing_get_labor",
    "get_wo_labor_activities": "executing_get_labor_activities",
    "get_site": "executing_get_site",
    "get_wo_part_line": "executing_get_part_line",
}

_EXECUTING_STAGES = frozenset(
    {
        "executing_list",
        "executing_get",
        "executing_get_parts",
        "executing_get_part_line",
        "executing_get_labor",
        "executing_get_labor_activities",
        "executing_get_site",
        "executing_create",
        "executing_close",
        "executing_reopen",
        "executing_remark",
    }
)
_CONFIRM_KEYWORDS = {
    "yes", "yeah", "yep", "confirm", "confirmed", "go ahead", "proceed",
    "that's correct", "sounds good", "do it", "create it", "submit",
}
_DENY_KEYWORDS = {"no", "cancel", "stop", "wait", "not yet", "hold on", "change"}


def _missing_search_criteria(filters: dict, multi_codes: bool) -> list[str]:
    if api._has_search_criteria(filters, multi_codes):
        return []
    missing: list[str] = []
    if multi_codes and not filters.get("customer_code"):
        missing.append("Customer Code")
    missing.append("Customer Call Number, Site ID, Model, Serial, or WO Number")
    return missing


def _extract_search_filters_from_text(text: str) -> dict:
    """Best-effort extraction of search filters from user utterance."""
    lower = text.lower()
    found: dict = {}
    patterns = [
        ("customer_code", r"customer\s+(?:code|id)\s*(?:is|=|:)?\s*([A-Za-z0-9\-]+)"),
        ("cust_call", r"customer\s+call(?:\s+number)?\s*#?\s*([A-Za-z0-9\-]+)"),
        ("cust_call", r"call\s+number\s*#?\s*([A-Za-z0-9\-]+)"),
        ("site_id", r"site\s*(?:id)?\s*#?\s*([A-Za-z0-9\-]+)"),
        ("serial", r"serial(?:\s+number)?\s*#?\s*([A-Za-z0-9\-]+)"),
        ("model", r"model\s*#?\s*([A-Za-z0-9\-]+)"),
        ("wo_number", r"\bwork\s+orders?\s*#?\s*([A-Za-z]*\d+[A-Za-z0-9]*)"),
        ("wo_number", r"\bwo\b\s*#?\s*([A-Za-z]*\d+[A-Za-z0-9]*)"),
    ]
    for key, pattern in patterns:
        match = re.search(pattern, lower, re.IGNORECASE)
        if match and key not in found:
            found[key] = match.group(1).strip()
    limit_match = re.search(r"\b(?:last|latest|top|first)\s+(\d+)\b", lower)
    if limit_match:
        found["result_limit"] = int(limit_match.group(1))
    else:
        word_match = re.search(r"\b(?:last|latest|top|first)\s+(one|two|three|four|five|six|seven|eight|nine|ten)\b", lower)
        if word_match:
            word_to_int = {
                "one": 1,
                "two": 2,
                "three": 3,
                "four": 4,
                "five": 5,
                "six": 6,
                "seven": 7,
                "eight": 8,
                "nine": 9,
                "ten": 10,
            }
            found["result_limit"] = word_to_int[word_match.group(1)]
    return found


def _is_search_request(text: str) -> bool:
    lower = text.lower()
    extracted_filters = _extract_search_filters_from_text(text)
    if extracted_filters:
        return True
    if any(k in lower for k in _LIST_SIMPLE_KW):
        if any(k in lower for k in ("find", "search", "lookup", "look up")):
            return True
        return False
    if any(k in lower for k in _SEARCH_KW):
        return True
    if "find" in lower and "order" in lower:
        return True
    if "search" in lower and "order" in lower:
        return True
    return False


def _merge_search_filters(existing: dict, incoming: dict) -> dict:
    merged = api._normalize_search_filters(existing)
    for key, val in api._normalize_search_filters(incoming).items():
        merged[key] = val
    return merged


def _build_search_summary(filters: dict) -> str:
    parts = []
    if filters.get("customer_code"):
        parts.append(f"customer {filters['customer_code']}")
    if filters.get("cust_call"):
        parts.append(f"call number {filters['cust_call']}")
    if filters.get("site_id"):
        parts.append(f"site {filters['site_id']}")
    if filters.get("model"):
        parts.append(f"model {filters['model']}")
    if filters.get("serial"):
        parts.append(f"serial {filters['serial']}")
    if filters.get("wo_number"):
        parts.append(f"WO {filters['wo_number']}")
    if filters.get("result_limit"):
        parts.append(f"last {filters['result_limit']} result(s)")
    if not parts:
        return "Tell me what to search for: customer call number, site ID, model, serial, or WO number."
    return "Searching for work orders with " + ", ".join(parts) + "."


def _detect_days_back(text: str) -> int | None:
    lower = text.lower()
    month_match = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\b(?:\s+month)?\s+(\d{4})",
        lower,
    )
    if month_match:
        month_names = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
        }
        target_month = month_names[month_match.group(1)]
        target_year = int(month_match.group(2))
        target = datetime.date(target_year, target_month, 1)
        today = datetime.date.today()
        if target > today:
            # Use a large lookback for future month requests so we avoid
            # collapsing back to the default 90-day query window.
            return 3650
        return max((today - target).days + 31, 31)
    beyond_days = re.search(r"beyond\s+last\s+(\d+)\s+days?", lower)
    if beyond_days:
        base = int(beyond_days.group(1))
        return max(base * 2, 365)
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
    # Word-number + unit, e.g. "about eight months", "two years".
    _UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
    _WORD_NUM = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    }
    wm = re.search(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+(day|week|month|year)s?\b",
        lower,
    )
    if wm:
        return _WORD_NUM[wm.group(1)] * _UNIT_DAYS[wm.group(2)]
    # Generic "N <unit>" anywhere — catches "to 40 days", "about 8 months",
    # "increase lookback to 40 days" (no "last"/"back" needed). Prefer the last
    # number that carries a unit, so "back 2 to 40 days" → 40 days.
    matches = re.findall(r"(\d+)\s*(day|week|month|year)s?\b", lower)
    if matches:
        n, unit = matches[-1]
        return int(n) * _UNIT_DAYS[unit]
    if any(k in lower for k in ("beyond", "further back", "longer", "more history", "all time", "ever")):
        return 730
    return None


def _extract_part_line_number(text: str) -> int | None:
    lower = text.lower()
    for pattern in (
        r"part\s*line\s*#?\s*(\d+)",
        r"line\s*#?\s*(\d+)",
        r"line\s+(\d+)\s+",
    ):
        match = re.search(pattern, lower)
        if match:
            return int(match.group(1))
    return None


_CLOSE_KW = {
    "close wo", "close order", "close the work", "close this work",
    "mark complete", "mark wo complete", "complete work order", "resolve work order",
    "close call",
}
_REOPEN_KW = {"reopen", "re-open", "re open", "open again", "open it back"}
_REMARK_TRIGGER_KW = {"add", "leave", "write", "log", "post"}
_REMARK_TARGET_KW = {"remark", "note", "comment"}


def _extract_wo_number_from_text(text: str) -> str | None:
    for pattern in (
        r"\b(?:wo|work\s+order)\s*#?\s*([A-Za-z0-9]+)",
        r"\b(WU\d+)\b",
        r"\b([A-Z]{2}\d{5,})\b",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def _extract_close_reason_from_text(text: str) -> str | None:
    for pattern in (
        r"reason\s*:\s*(.+)",
        r"because\s+(.+)",
        r"due to\s+(.+)",
        r"customer\s+confirmed\s+(.+)",
        r"resolution\s*:\s*(.+)",
    ):
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            reason = match.group(1).strip().rstrip(".")
            if len(reason) >= api._MIN_LIFECYCLE_REASON_LEN:
                return reason
    return None


def _extract_reopen_reason_from_text(text: str) -> str | None:
    for pattern in (
        r"reason\s*:\s*(.+)",
        r"because\s+(.+)",
        r"due to\s+(.+)",
        r"reopen(?:ed)?\s+(?:wo|work order|it)?\s*[-,:]?\s*(.+)",
        r"issue\s+came\s+back[,:]?\s*(.+)",
    ):
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            reason = match.group(1).strip().rstrip(".")
            if len(reason) >= api._MIN_LIFECYCLE_REASON_LEN:
                return reason
    return None


def _detect_lifecycle_intent(text: str) -> str | None:
    lower = text.lower()
    # "closed work orders" is a read/search request, not a lifecycle mutation.
    if re.search(r"\bclosed\s+work\s+orders?\b", lower) or re.search(r"\bclosed\s+orders?\b", lower):
        return None
    if any(k in lower for k in _REOPEN_KW):
        return "reopen_wo"
    if any(k in lower for k in _CLOSE_KW):
        return "close_wo"
    if "close" in lower and ("work order" in lower or " wo" in lower or re.search(r"\bwo\b", lower)):
        return "close_wo"
    return None


# "add a remark to a work order" captures "to a work order" — a reference to the
# target, not remark content. Reject these so they don't become the remark text.
_NON_REMARK_TAIL = re.compile(
    r"^(?:to|on|for|about|in)\s+(?:a|an|the|this|that|my)?\s*"
    r"(?:work\s*order|wo|order|call|ticket|it|this|that)\s*[?.!]*$",
    re.IGNORECASE,
)


def _extract_remark_text_from_text(text: str) -> str | None:
    for pattern in (
        r"(?:remark|note|comment)\s*[:\-]\s*(.+)",
        r"(?:add|leave|write|log)\s+(?:a\s+)?(?:remark|note|comment)\s+(?:that\s+)?(.+)",
    ):
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            remark = match.group(1).strip().rstrip(".")
            if _NON_REMARK_TAIL.match(remark):
                continue
            if len(remark) >= api._MIN_LIFECYCLE_REASON_LEN:
                return remark
    return None


_REMARK_READ_VERBS = re.compile(r"\b(read|tell|show|list|what|which|view|see|display|give|any)\b")


def _detect_remark_intent(text: str) -> bool:
    """True only for a remark WRITE. A read ('read me the logged remarks', 'what
    are the remarks') is not a write — and 'logged'/'blog' must not match 'log'."""
    lower = text.lower()
    if _REMARK_READ_VERBS.search(lower):
        return False
    has_trigger = any(re.search(rf"\b{re.escape(k)}\b", lower) for k in _REMARK_TRIGGER_KW)
    has_target = any(k in lower for k in _REMARK_TARGET_KW)
    return has_trigger and has_target


def _build_remark_summary(wo_number: str, detail: dict | None, remark_text: str) -> str:
    d = detail or {}
    cust = d.get("custcode", "")
    status = d.get("vstatus", "")
    parts = [
        f"Add this remark to work order {wo_number}",
        f"customer {cust}" if cust else "",
        f"status {status}" if status else "",
    ]
    summary = ", ".join(p for p in parts if p) + f": {remark_text.strip()}."
    return summary + " Say yes to confirm or no to change it."


def _route_remark_flow(
    *,
    wo_number: str | None,
    remark_text: str | None,
    user_message: str,
) -> tuple[str, str | None, str]:
    wo = (wo_number or "").strip() or _extract_wo_number_from_text(user_message or "")
    text = (remark_text or "").strip() or (_extract_remark_text_from_text(user_message or "") or "")
    if not wo:
        return "collecting_wo_number", None, text
    if len(text) < api._MIN_LIFECYCLE_REASON_LEN:
        return "collecting_remark_text", wo, text
    return "confirming_remark", wo, text


def _merge_close_fields(existing: dict, incoming: dict) -> dict:
    merged = api._normalize_close_fields(existing)
    for key, val in api._normalize_close_fields(incoming).items():
        merged[key] = val
    return merged


def _build_close_summary(wo_number: str, detail: dict | None, close_fields: dict) -> str:
    d = detail or {}
    cust = d.get("custcode", "")
    city = d.get("city", "")
    status = d.get("vstatus", "")
    last_stop = d.get("laststop", "")
    closed = d.get("closed", "")
    reason = api._normalize_close_fields(close_fields).get("Close Reason", "")
    parts = [
        f"Close work order {wo_number}",
        f"customer {cust}" if cust else "",
        f"in {city}" if city else "",
        f"status {status}" if status else "",
        f"last stop {last_stop}" if last_stop else "",
    ]
    summary = ", ".join(p for p in parts if p) + f". Reason: {reason}."
    if closed:
        summary += f" (Currently shows closed date {closed}.)"
    return summary + " Say yes to confirm or no to change something."


def _build_reopen_summary(wo_number: str, detail: dict | None, reopen_reason: str) -> str:
    d = detail or {}
    cust = d.get("custcode", "")
    status = d.get("vstatus", "")
    closed = d.get("closed", "")
    parts = [
        f"Reopen work order {wo_number}",
        f"customer {cust}" if cust else "",
        f"status {status}" if status else "",
    ]
    summary = ", ".join(p for p in parts if p) + f". Reason: {reopen_reason.strip()}."
    if closed:
        summary += f" Closed date on file: {closed}."
    return summary + " Say yes to confirm or no to change something."


def _route_close_flow(
    *,
    wo_number: str | None,
    close_fields: dict,
    user_message: str,
) -> tuple[str, str | None, dict]:
    wo = (wo_number or "").strip() or _extract_wo_number_from_text(user_message or "")
    fields = _merge_close_fields(close_fields, {})
    extracted = _extract_close_reason_from_text(user_message or "")
    if extracted:
        fields["Close Reason"] = extracted
    if not wo:
        return "collecting_wo_number", None, fields
    if api.missing_close_fields(fields):
        return "collecting_close_reason", wo, fields
    return "confirming_close", wo, fields


def _route_reopen_flow(
    *,
    wo_number: str | None,
    reopen_reason: str | None,
    user_message: str,
) -> tuple[str, str | None, str]:
    wo = (wo_number or "").strip() or _extract_wo_number_from_text(user_message or "")
    reason = (reopen_reason or "").strip() or (_extract_reopen_reason_from_text(user_message or "") or "")
    if not wo:
        return "collecting_wo_number", None, reason
    if len(reason) < api._MIN_LIFECYCLE_REASON_LEN:
        return "collecting_reopen_reason", wo, reason
    return "confirming_reopen", wo, reason


def _preflight_for_confirm(
    state: WWTSState,
    *,
    intent: str,
    wo_number: str,
    customer_codes: list,
) -> tuple[dict | None, str | None]:
    """Return (detail, error_message)."""
    context = state.get("context") or {}
    session = context.get("wwts_session")
    user_id = state.get("user_id", "")
    if not session or not wo_number:
        return state.get("wo_detail"), None
    if intent == "close_wo":
        pre = api.preflight_close_workorder(user_id, session, wo_number, customer_codes)
    else:
        pre = api.preflight_reopen_workorder(user_id, session, wo_number, customer_codes)
    if not pre["success"]:
        return pre.get("detail"), _friendly_err(pre.get("error"))
    return pre.get("detail"), None


def _detect_focused_read_intent(text: str) -> str | None:
    """Dedicated Phase 2 read intents (narrower than full get_wo)."""
    lower = text.lower()
    if any(k in lower for k in _PART_LINE_KEYWORDS) or re.search(
        r"line\s*#?\s*\d+", lower
    ):
        return "get_wo_part_line"
    if any(k in lower for k in _LABOR_ACT_KEYWORDS):
        return "get_wo_labor_activities"
    if any(k in lower for k in _SITE_FOCUS_KEYWORDS):
        return "get_site"
    if any(k in lower for k in ("labor items", "labor on", "labor for")) and "activit" not in lower:
        return "get_wo_labor"
    if any(k in lower for k in ("what parts", "parts on", "part list", "parts for")):
        return "get_wo_parts"
    if any(k in lower for k in _PARTS_KEYWORDS) and "line" not in lower:
        return "get_wo_parts"
    if any(k in lower for k in _LABOR_KEYWORDS) and "activit" not in lower:
        return "get_wo_labor"
    return None


def _route_focused_read(
    focused_intent: str,
    *,
    wo_number: str | None,
    wo_part_line: int | None,
    user_message: str,
    stage: str,
) -> tuple[str, str | None, int | None]:
    """Return (new_stage, wo_number, wo_part_line)."""
    wo = wo_number
    line = wo_part_line or _extract_part_line_number(user_message)

    if focused_intent == "get_wo_part_line":
        if not wo:
            return "collecting_wo_number", wo, line
        if not line:
            if stage == "collecting_wo_part_line" and user_message:
                line = _extract_part_line_number(user_message)
            if line:
                return "executing_get_part_line", wo, line
            return "collecting_wo_part_line", wo, line
        return "executing_get_part_line", wo, line

    if not wo:
        return "collecting_wo_number", wo, line
    return _FOCUS_STAGE_BY_INTENT[focused_intent], wo, line


_REMARKS_READ_KEYWORDS = {
    "remark", "remarks", "note", "notes", "comment", "comments",
    "activity history", "history", "updates", "update log", "log",
}


def _detect_get_focus(text: str) -> str | None:
    lower = text.lower()
    # Remarks read ("tell me the remarks/notes/history") — but NOT a write
    # ("add a remark"), which _detect_remark_intent handles separately.
    if any(k in lower for k in _REMARKS_READ_KEYWORDS) and not _detect_remark_intent(text):
        return "remarks"
    if any(k in lower for k in _PARTS_KEYWORDS):
        return "parts"
    if any(k in lower for k in _LABOR_KEYWORDS):
        return "labor"
    return None


def _word_in(text: str, keyword: str) -> bool:
    """Whole-word/phrase match so 'no' doesn't match inside 'not'/'notebook'."""
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def _is_confirm_utterance(text: str) -> bool:
    lower = text.strip().lower().rstrip(".!")
    if lower in _CONFIRM_KEYWORDS:
        return True
    return any(_word_in(lower, k) for k in ("yes", "confirm", "go ahead", "proceed"))


def _is_deny_utterance(text: str) -> bool:
    lower = text.strip().lower()
    return any(_word_in(lower, k) for k in _DENY_KEYWORDS)


def _build_create_summary(fields: dict) -> str:
    customer = fields.get("Customer Code", "")
    product = fields.get("Product Reference", "")
    contact = fields.get("Contact Name", "")
    phone = fields.get("Contact Phone", "")
    site = fields.get("Site ID", "")
    city = fields.get("Customer City", "")
    state = fields.get("Customer State", "")
    postal = fields.get("Customer Postal Code", "")
    if site:
        location = f"Site ID {site}"
    elif city:
        location = f"{city}, {state} {postal}".strip()
    else:
        location = "location not set"
    return (
        f"Customer {customer}, product {product}, contact {contact}, phone {phone}, "
        f"{location}. Should I create this work order?"
    )


def _detect_wo_status(text: str) -> str | None:
    """Keyword-level status detection — used to override LLM extraction when it misses."""
    lower = text.lower()
    if re.search(r"\bnot\s+open\b", lower) or re.search(r"\bnon[-\s]?open\b", lower):
        return "C"
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
- Search filters so far: {search_filters}
- Missing search criteria: {missing_search}

════════════════════════════════════════════
ROUTING RULES  (apply to EVERY stage)
════════════════════════════════════════════
Match the user message against these patterns and set new_stage IMMEDIATELY:

→ new_stage = "executing_list" with intent list_wo  (no confirmation needed)
  Counts of WOs, open/closed lists, "how many", "list my work orders", "show open orders"
  WITHOUT a specific CustCall/SiteID/Model/Serial/WO filter.
  Set extracted.wo_status = "O" (default), "C" closed, "A" all.

→ new_stage = "collecting_search_criteria" OR executing_list with intent search_wo
  User wants to FIND/SEARCH orders by criteria: customer call number, site ID, model,
  serial, vendor call, or a specific WO number in search (not full WO detail).
  Set intent = search_wo. Merge criteria into extracted.search_filters.
  If at least one search filter is present (and customer code when multiple tenants)
  → executing_list immediately. Otherwise collecting_search_criteria.

→ new_stage = "executing_get"  (set extracted.wo_number too)
  User provides a WO/order number explicitly, OR asks for details/status/history/updates
  of a specific order AND a WO number is already in context ({wo_number}).
  Also when WO number is known and user asks about parts, shipped items, labor,
  technician, or CSR on that order.

→ new_stage = "collecting_wo_number"
  User asks for details/status of a WO but no WO number is known yet.

→ new_stage = "collecting_create"
  User wants to create / open / file a new work order.

→ Lifecycle write intents (WO number required unless already in context):
  close_wo:
    - If WO missing -> collecting_wo_number
    - If close reason missing/too short -> collecting_close_reason
    - When WO + reason available -> confirming_close (never jump directly to execute)
    - On explicit yes in confirming_close -> executing_close
  reopen_wo:
    - If WO missing -> collecting_wo_number
    - If reopen reason missing/too short -> collecting_reopen_reason
    - When WO + reason available -> confirming_reopen (never jump directly to execute)
    - On explicit yes in confirming_reopen -> executing_reopen
  add_wo_remark:
    - If WO missing -> collecting_wo_number
    - If remark text missing/too short -> collecting_remark_text
    - When WO + remark text available -> confirming_remark (never jump directly to execute)
    - On explicit yes in confirming_remark -> executing_remark

→ Focused read intents (WO number required unless already in context):
  executing_get_parts — parts list only (intent get_wo_parts)
  executing_get_part_line — one part line (intent get_wo_part_line; need line number)
  executing_get_labor — labor/tech items (intent get_wo_labor)
  executing_get_labor_activities — labor activities (intent get_wo_labor_activities)
  executing_get_site — site/location for WO (intent get_site)
  collecting_wo_part_line — user wants part line detail but line number missing

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
  Ask for the WO number. When user provides any number → route to the matching executing_* stage.

COLLECTING_WO_PART_LINE
  Ask which part line number. When provided → executing_get_part_line.

COLLECTING_SEARCH_CRITERIA
  Collect search filters (at most 2 missing per reply). When enough → executing_list + search_wo.
  Missing: {missing_search}

COLLECTING_CREATE
  Ask for missing fields (at most 2 per reply). When all collected → confirming_create.
  Missing: {missing_fields}

CONFIRMING_CREATE
  User must confirm before create runs. If they say yes/confirm/go ahead → executing_create.
  If they say no/cancel/wait → collecting_create. Otherwise repeat the summary and ask again.
  PRIORITY: If "Customer Code" is in the missing list AND multiple codes are available,
  present the full list from "Available customer codes" and ask the user to choose ONE
  before asking for anything else. Extract the chosen code into extracted.create_fields.Customer Code.
  NOTE: City + State + Postal Code is normally sufficient for location — do NOT ask for a
  street address up front. BUT if the system reports the address could not be validated,
  ask for and capture the street address into extracted.create_fields."Customer Address".
  NOTE: Only extract "Contact Name" when the user explicitly names the contact
  (e.g. "contact name is X", "the contact is X"). Do NOT extract it from possessive
  or qualifying phrases like "phone number for X" or "number for X".

COLLECTING_CLOSE_REASON
  Collect a close reason (minimum 5 characters). When reason is valid and WO known:
  run preflight intent checks and move to confirming_close.

CONFIRMING_CLOSE
  User must explicitly confirm before close executes.
  yes/confirm/go ahead -> executing_close
  no/cancel -> collecting_close_reason
  otherwise restate summary and ask yes/no.

COLLECTING_REOPEN_REASON
  Collect reopen reason (minimum 5 characters). When reason is valid and WO known:
  run preflight intent checks and move to confirming_reopen.

CONFIRMING_REOPEN
  User must explicitly confirm before reopen executes.
  yes/confirm/go ahead -> executing_reopen
  no/cancel -> collecting_reopen_reason
  otherwise restate summary and ask yes/no.

COLLECTING_REMARK_TEXT
  Collect remark text (minimum 5 characters). When WO + text are valid:
  run preflight scope checks and move to confirming_remark.

CONFIRMING_REMARK
  User must explicitly confirm before remark write executes.
  yes/confirm/go ahead -> executing_remark
  no/cancel -> collecting_remark_text
  otherwise restate summary and ask yes/no.

DONE
  Previous task is complete. Acknowledge in ≤1 sentence.
  Then apply routing rules to the new message — route immediately if a task is present.
  If no new task → ask what else they need, set new_stage = "intent".

════════════════════════════════════════════
Reply ONLY with valid JSON — no markdown, no extra text:
{{
  "response": "...",
  "speak": "...",
  "new_stage": "intent|collecting_wo_number|collecting_wo_part_line|collecting_search_criteria|collecting_create|confirming_create|collecting_close_reason|confirming_close|collecting_reopen_reason|confirming_reopen|collecting_remark_text|confirming_remark|executing_list|executing_get|executing_get_parts|executing_get_part_line|executing_get_labor|executing_get_labor_activities|executing_get_site|executing_create|executing_close|executing_reopen|executing_remark|done",
  "extracted": {{
    "intent": "list_wo|search_wo|get_wo|get_wo_parts|get_wo_part_line|get_wo_labor|get_wo_labor_activities|get_site|create_wo|close_wo|reopen_wo|add_wo_remark|null",
    "wo_number": "string or null",
    "wo_part_line": "integer or null",
    "wo_status": "O|C|A|null",
    "search_filters": {{
      "customer_code": "string or null",
      "cust_call": "string or null",
      "site_id": "string or null",
      "model": "string or null",
      "serial": "string or null",
      "wo_number": "string or null"
    }},
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
    }},
    "close_fields": {{
      "Close Reason": "string or null"
    }},
    "reopen_reason": "string or null",
    "remark_text": "string or null"
  }}
}}"""


_TS_STAGES = {
    "ts_collecting_name",
    "ts_confirm_issue",
    "ts_collecting_product",
    "ts_collecting_issue",
    "ts_troubleshooting",
}
_TS_MAX_TROUBLESHOOTS = 2
_TS_MAX_STEPS_PER = 5
_TS_DEVICE_KW = {
    "laptop", "notebook", "computer", "machine", " pc ", "device", "dell", "latitude",
    "monitor", "printer", "server", "desktop", "workstation", "tablet",
}
_TS_PROBLEM_KW = {
    "not working", "won't", "wont", "doesn't", "doesnt", "broken", "issue",
    "problem", "error", "dead", "slow", "overheat", "hot", "crash", "freeze",
    "frozen", "black screen", "blue screen", "not turn", "won't turn", "fan",
    "battery", "charge", "charging", "boot", "power", "stuck", "trouble",
    "shutting down", "shuts down", "not booting", "blinking", "beeping",
    "no display", "malfunction", "fault", "faulty", "having trouble",
}


def _detect_troubleshoot_intent(text: str) -> bool:
    """A device problem the user wants help fixing (laptop won't turn on, etc.)."""
    lower = f" {(text or '').lower()} "
    if "troubleshoot" in lower:
        return True
    has_device = any(k in lower for k in _TS_DEVICE_KW)
    has_problem = any(k in lower for k in _TS_PROBLEM_KW)
    return has_device and has_problem


def _mentions_issue(text: str) -> bool:
    lower = f" {(text or '').lower()} "
    return any(k in lower for k in _TS_PROBLEM_KW)


# Words that carry no symptom on their own — "yes I'm facing some issues" is not
# a concrete problem description, so we ask for specifics before troubleshooting.
_VAGUE_ISSUE_WORDS = {
    "yes", "yeah", "yep", "no", "issue", "issues", "problem", "problems", "trouble",
    "facing", "some", "having", "difficulty", "difficulties", "technical", "a", "an",
    "the", "with", "it", "its", "my", "im", "i", "am", "is", "are", "and", "to",
    "device", "help", "me", "of", "kind", "sort", "so",
}


def _is_concrete_issue(text: str) -> bool:
    """Concrete = names an actual symptom, not just "I have an issue" or a bare
    device name. Either a known symptom keyword, or a genuinely detailed sentence."""
    lower = (text or "").lower()
    specific = _TS_PROBLEM_KW - {"issue", "problem", "trouble"}
    if any(k in f" {lower} " for k in specific):
        return True
    words = [w for w in re.findall(r"[a-z]+", lower) if w not in _VAGUE_ISSUE_WORDS]
    return len(words) >= 5


_NAME_PATTERNS = (
    r"\bmy name is\s+([A-Za-z][A-Za-z .'-]{1,40})",
    r"\bi am\s+([A-Za-z][A-Za-z .'-]{1,40})",
    r"\bi'?m\s+([A-Za-z][A-Za-z .'-]{1,40})",
    r"\bthis is\s+([A-Za-z][A-Za-z .'-]{1,40})",
    r"\bit'?s\s+([A-Za-z][A-Za-z .'-]{1,40})",
    r"\bname'?s\s+([A-Za-z][A-Za-z .'-]{1,40})",
)


def _clean_name(raw: str) -> str:
    name = (raw or "").strip().rstrip(".!,")
    # stop at a connector so "Rachit and my laptop..." -> "Rachit"
    name = re.split(r"\s+(?:and|,|but|\.)\s+", name, maxsplit=1)[0].strip()
    return name.title() if name.islower() else name


def _extract_name(text: str) -> str | None:
    t = (text or "").strip()
    for pat in _NAME_PATTERNS:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            return _clean_name(m.group(1))
    # Bare name reply ("Rachit", "Rachit Gandhi") — short, alphabetic, no issue.
    if not _mentions_issue(t):
        words = t.rstrip(".!,").split()
        if 1 <= len(words) <= 3 and all(re.fullmatch(r"[A-Za-z.'\-]+", w) for w in words):
            return _clean_name(t.rstrip(".!,"))
    return None


_PRODUCT_STOPWORDS = {
    "is", "for", "the", "of", "a", "an", "to", "this", "that", "device", "number",
    "my", "with", "it", "and", "reference", "ref", "product", "model", "are", "no",
    "yes", "yeah", "nope", "ok", "okay",
}


def _extract_product_ref(text: str) -> str | None:
    # After the keyword, skip filler words ("for the device is") and take the
    # first real code token — so "reference for the device is BDQ" → BDQ.
    m = re.search(
        r"\b(?:product\s+reference|product\s+ref|reference|product|model|ref)\b"
        r"[\s:=]*((?:[A-Za-z0-9][A-Za-z0-9\-]{1,14}\s*){1,6})",
        text or "",
        re.IGNORECASE,
    )
    if m:
        for tok in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{1,14}", m.group(1)):
            if tok.lower() not in _PRODUCT_STOPWORDS:
                return tok.upper()
    # Bare code reply ("BDQ").
    m2 = re.fullmatch(r"\s*([A-Za-z0-9][A-Za-z0-9\-]{1,14})\s*[.!]?\s*", text or "")
    if m2:
        cand = m2.group(1).strip()
        if cand.lower() not in _PRODUCT_STOPWORDS:
            return cand.upper()
    return None


_DEVICE_BRAND_RE = re.compile(
    r"\b(hp|dell|lenovo|apple|macbook|asus|acer|microsoft|surface|elitebook|"
    r"thinkpad|probook|ideapad|latitude|inspiron|thinkcentre|chromebook)\b"
    r"(?:\s+[A-Za-z0-9]+){0,2}",
    re.IGNORECASE,
)
_DEVICE_NOUN_RE = re.compile(
    r"\b(laptop|notebook|desktop|monitor|printer|tablet|server|workstation|pc)\b",
    re.IGNORECASE,
)


def _extract_device(text: str) -> str | None:
    """Pull a short device/brand phrase from free text ('my HP EliteBook' → 'HP EliteBook')."""
    m = _DEVICE_BRAND_RE.search(text or "")
    if m:
        return re.sub(r"\s+", " ", m.group(0)).strip()
    m2 = _DEVICE_NOUN_RE.search(text or "")
    if m2:
        return m2.group(1)
    return None


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return len(a) + len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            curr.append(min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = curr
    return prev[-1]


def _closest_product_code(ref: str, products: list) -> str | None:
    """Snap a (possibly mis-heard) product reference to the closest real
    CustomerPartMaster in the customer's product list. None if nothing is close."""
    target = (ref or "").strip().upper()
    codes = [str(p.get("code", "")).strip().upper() for p in (products or []) if p.get("code")]
    if not target or not codes:
        return None
    if target in codes:
        return target
    best, best_d = None, 99
    for c in codes:
        if abs(len(c) - len(target)) > 2:
            continue
        d = _edit_distance(target, c)
        if d < best_d:
            best, best_d = c, d
    return best if best_d <= 2 else None


def _extract_product_ref_correction(text: str) -> str | None:
    """Pull the intended product code from a correction phrasing:
    'change [the product] [from X] to Y' / 'product is Y' / 'Y not X'."""
    t = text or ""
    if re.search(r"\b(change|update|correct|make it|set|fix)\b", t, re.IGNORECASE) or re.search(
        r"\bproduct\b", t, re.IGNORECASE
    ):
        m = re.search(r"\bto\s+([A-Za-z][A-Za-z0-9\-]{1,14})\b", t, re.IGNORECASE)
        if m and m.group(1).lower() not in _PRODUCT_STOPWORDS:
            return m.group(1).upper()
    m = re.search(
        r"\bproduct(?:\s+reference)?\s+(?:is\s+|=\s*|:\s*)?([A-Za-z][A-Za-z0-9\-]{1,14})\b",
        t, re.IGNORECASE,
    )
    if m and m.group(1).lower() not in _PRODUCT_STOPWORDS:
        return m.group(1).upper()
    m = re.search(r"\b([A-Za-z][A-Za-z0-9\-]{1,14})\s+not\s+[A-Za-z][A-Za-z0-9\-]{1,14}\b", t, re.IGNORECASE)
    if m and m.group(1).lower() not in _PRODUCT_STOPWORDS:
        return m.group(1).upper()
    return None


def _resolve_product(state: WWTSState, context: dict, product_ref: str) -> tuple[str, str]:
    """Best-effort product lookup. Returns (description, canonical_ref).

    With a single customer code we query it directly; with several we probe each
    (capped) until the reference is found. If the exact code isn't in the catalog,
    fuzzy-snap a mis-heard code to the closest real one (BBQ→BDQ)."""
    if not product_ref:
        return "", product_ref
    session = context.get("wwts_session")
    if not session:
        return "", product_ref
    user_id = state.get("user_id", "")
    cc = context.get("customer_code")
    if cc:
        codes = [cc]
    else:
        codes = [
            (c.get("code") if isinstance(c, dict) else c)
            for c in (context.get("customer_codes") or [])[:8]
        ]
    for code in codes:
        look = api.lookup_product_reference(user_id, session, code, product_ref)
        if not look.get("success"):
            continue
        if look.get("product"):
            return look["product"].get("description", "") or "", product_ref
        snapped = _closest_product_code(product_ref, look.get("products") or [])
        if snapped:
            desc = next(
                (p.get("description", "") for p in look["products"] if str(p.get("code", "")).upper() == snapped),
                "",
            )
            return desc, snapped
    return "", product_ref


def _clamp_troubleshoots(items: list) -> list:
    out: list[dict] = []
    for t in (items or [])[:_TS_MAX_TROUBLESHOOTS]:
        steps = [str(s).strip() for s in (t.get("steps") or []) if str(s).strip()]
        steps = steps[:_TS_MAX_STEPS_PER]
        if steps:
            out.append({"title": str(t.get("title") or "Troubleshooting steps").strip(), "steps": steps})
    # Hard cap of 10 steps total across both troubleshoots.
    total = 0
    capped: list[dict] = []
    for t in out:
        room = max(0, 10 - total)
        if room <= 0:
            break
        t["steps"] = t["steps"][:room]
        total += len(t["steps"])
        capped.append(t)
    return capped


def _llm_troubleshoots(product_label: str, issue: str) -> list:
    if not os.getenv("OPENAI_API_KEY"):
        return []
    try:
        from langchain_openai import ChatOpenAI

        model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
        llm = ChatOpenAI(model=model, temperature=0.2)
        sys = (
            "You are a hardware support expert for WWTS field service. Given a device and a "
            "reported issue, produce AT MOST 2 short troubleshooting procedures, most-likely "
            "fix first. Each procedure has a short title and 2-5 clear imperative steps a "
            "non-technical caller can follow by phone. Keep total steps across both at or "
            "under 10 — fewer, quicker steps are better.\n"
            "IMPORTANT: Do NOT tell the customer to contact the manufacturer, HP, Dell, a "
            "help desk, or any third party, and do NOT tell them to call or visit external "
            "support — WWTS will dispatch a technician via the work order we are filing. If "
            "the steps don't fix it, the final step should say a WWTS technician will be "
            "dispatched to service it.\n"
            "Reply ONLY with JSON, no markdown:\n"
            '{"troubleshoots":[{"title":"...","steps":["...","..."]}]}'
        )
        res = llm.invoke(
            [
                {"role": "system", "content": sys},
                {"role": "user", "content": f"Device: {product_label}\nIssue: {issue}"},
            ]
        )
        data = _parse_json(res.content)
        return data.get("troubleshoots") or []
    except Exception:
        return []


def _fallback_troubleshoots(product_label: str, issue: str) -> list:
    out: list[dict] = []
    entry = faq.match_faq(issue)
    if entry:
        out.append({"title": entry["title"], "steps": entry.get("steps") or []})
    generic = {
        "title": "Power and adapter check",
        "steps": [
            "Disconnect the charger and any USB devices, then hold the power button for 30 seconds to drain residual power.",
            "Reconnect the original charger and confirm the charging light comes on.",
            "Press power once and watch for keyboard lights or fan noise, and note any error message.",
        ],
    }
    display = {
        "title": "Display and connection check",
        "steps": [
            "Connect an external monitor to check whether the screen panel is the problem.",
            "Remove any dock or USB hub and try powering on the device directly.",
        ],
    }
    if not out:
        return [generic, display]
    if len(out) < 2:
        out.append(generic if out[0]["title"] != generic["title"] else display)
    return out


def _generate_troubleshoots(product_label: str, issue: str) -> list:
    items = _llm_troubleshoots(product_label, issue)
    if not items:
        items = _fallback_troubleshoots(product_label, issue)
    items = _clamp_troubleshoots(items)
    return items or _clamp_troubleshoots(_fallback_troubleshoots(product_label, issue))


def _format_troubleshoot(ts: dict, index: int) -> str:
    lines = [f"Troubleshoot {index}: {ts.get('title', '').strip()}".rstrip()]
    for i, step in enumerate(ts.get("steps", []), start=1):
        lines.append(f"  {i}. {step}")
    return "\n".join(lines)


def _ts_return(state: WWTSState, messages: list, reply: str, **updates) -> WWTSState:
    messages.append({"role": "assistant", "content": reply})
    out = {
        **state,
        "intent": "troubleshoot",
        "messages": messages,
        "final_answer": reply,
        "speak": reply,
        "requires_more_info": True,
    }
    out.update(updates)
    return out


def _enter_troubleshooting(
    state: WWTSState,
    messages: list,
    *,
    name: str,
    product_ref: str,
    product_desc: str,
    device: str,
    issue: str,
    lead: str,
) -> WWTSState:
    label = product_desc or device or product_ref or "the device"
    troubleshoots = _generate_troubleshoots(label, issue)
    first = troubleshoots[0]
    block = _format_troubleshoot(first, 1)
    pre = f"{lead} " if lead else ""
    reply = f"{pre}Let's try this first:\n\n{block}\n\nDid that resolve it? (yes / no)"
    return _ts_return(
        state,
        messages,
        reply,
        stage="ts_troubleshooting",
        ts_name=name or None,
        ts_product_ref=product_ref or None,
        ts_product_desc=product_desc or None,
        ts_device=device or None,
        ts_issue=issue,
        ts_troubleshoots=troubleshoots,
        ts_executed=1,
    )


def _ts_extract(messages: list, known: dict) -> dict:
    """Use the LLM to pull intake fields from natural conversation, in any order.

    Returns {name, product_reference, device, issue, has_symptom, declines_help}
    (any may be missing). Empty dict when no API key / on error — callers then
    fall back to the regex extractors so offline behaviour still works.
    """
    if not os.getenv("OPENAI_API_KEY"):
        return {}
    try:
        from langchain_openai import ChatOpenAI

        model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
        llm = ChatOpenAI(model=model, temperature=0)
        sys = (
            "You extract intake fields for a hardware support call. Read the WHOLE "
            "conversation — the caller may volunteer things in any order — and return "
            "ONLY JSON (no markdown):\n"
            "{\n"
            '  "name": caller name or null,\n'
            '  "product_reference": a short product CODE like "BDQ" or "AB12" (2-15 '
            "letters/digits; NEVER a word like for/the/device/reference) or null,\n"
            '  "device": the device described e.g. "HP EliteBook laptop" or null,\n'
            '  "issue": the concrete technical symptom in the caller\'s own words or null,\n'
            '  "has_symptom": true only if a real symptom is described (overheating, '
            'won\'t boot, slow, cracked screen...), false for vague "I have a problem",\n'
            '  "declines_help": true if the caller says they have NO technical issue or '
            "wants to stop/transfer\n"
            "}\n"
            "Use null when unknown; never guess a product code. Keep prior known values "
            f"unless the caller corrects them. Known so far: {json.dumps(known)}"
        )
        res = llm.invoke([{"role": "system", "content": sys}] + messages[-10:])
        data = _parse_json(res.content)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _handoff_to_create(
    state: WWTSState,
    messages: list,
    context: dict,
    *,
    name: str,
    product_ref: str,
    issue: str,
    resolved: bool,
) -> WWTSState:
    customer_code = context.get("customer_code", "")
    customer_codes = context.get("customer_codes") or []
    has_customer_code = bool(customer_code) or bool(customer_codes)
    multi_codes = len(customer_codes) > 1

    create_fields = _normalize_create_fields(dict(state.get("create_fields") or {}))
    if name and not create_fields.get("Contact Name"):
        create_fields["Contact Name"] = name
    if product_ref:
        create_fields["Product Reference"] = product_ref

    missing = _missing_create_fields(create_fields, has_customer_code, multi_codes)
    lead = (
        "Glad we got that working! I'll still log a work order so there's a record. "
        if resolved
        else "Thanks for trying those. I'll file a work order so a technician can take it from here. "
    )
    if missing:
        ask = lead + "To open it, I need your " + ", ".join(missing) + "."
        new_stage = "collecting_create"
    else:
        ask = lead + _build_create_summary(create_fields)
        new_stage = "confirming_create"
    messages.append({"role": "assistant", "content": ask})
    return {
        **state,
        "stage": new_stage,
        "intent": "create_wo",
        "create_fields": create_fields,
        "ts_name": name or None,
        "ts_product_ref": product_ref or None,
        "ts_issue": issue,
        "ts_resolved": resolved,
        "pending_troubleshoot": True,
        "messages": messages,
        "final_answer": ask,
        "speak": ask,
        "requires_more_info": True,
    }


def _handle_troubleshoot(
    state: WWTSState,
    messages: list,
    user_message: str,
    context: dict,
    *,
    fresh: bool,
) -> WWTSState:
    """Scripted support flow: greet → name → confirm issue → product (+lookup) →
    issue → generate & walk through ≤2 troubleshoots → hand off to create (which
    files the WO and logs the user comment + AI analysis as two remarks)."""
    stage = state.get("stage")
    name = (state.get("ts_name") or "").strip()
    issue = (state.get("ts_issue") or "").strip()
    product_ref = (state.get("ts_product_ref") or "").strip()
    product_desc = (state.get("ts_product_desc") or "").strip()
    device = (state.get("ts_device") or "").strip()

    # ---- Fresh entry: greet and ask for the caller's name -------------------
    if fresh:
        stashed = (user_message or "").strip() if _mentions_issue(user_message) else ""
        reply = "Hi, thanks for reaching WWTS support! Before we dig in — may I have your name?"
        return _ts_return(
            state, messages, reply,
            stage="ts_collecting_name",
            ts_name=None,
            ts_product_ref=None,
            ts_product_desc=None,
            ts_device=None,
            ts_troubleshoots=None,
            ts_executed=None,
            ts_resolved=None,
            ts_added_remarks=None,
            pending_troubleshoot=False,
            ts_issue=stashed or None,
        )

    # If the caller issues a clear work-order command mid-support (e.g. "list my
    # work orders", "create a WO", "look up WU123"), drop the support flow and let
    # normal routing handle it. Returning None signals the caller to fall through.
    if not _mentions_issue(user_message) and _keyword_stage(user_message or ""):
        return None

    # ---- Walking through the troubleshoots (yes/no — handle before intake) --
    if stage == "ts_troubleshooting":
        troubleshoots = state.get("ts_troubleshoots") or []
        executed = int(state.get("ts_executed") or 0)
        resolved = _is_confirm_utterance(user_message) and not _is_deny_utterance(user_message)
        if resolved:
            return _handoff_to_create(state, messages, context, name=name,
                                      product_ref=product_ref, issue=issue, resolved=True)
        if executed < len(troubleshoots) and executed < _TS_MAX_TROUBLESHOOTS:
            nxt = troubleshoots[executed]
            block = _format_troubleshoot(nxt, executed + 1)
            reply = f"No worries — let's try another approach.\n\n{block}\n\nDid that resolve it? (yes / no)"
            return _ts_return(state, messages, reply, stage="ts_troubleshooting",
                              ts_executed=executed + 1)
        return _handoff_to_create(state, messages, context, name=name,
                                  product_ref=product_ref, issue=issue, resolved=False)

    # ---- Understand the message (LLM-first, regex fallback), in any order ---
    ext = _ts_extract(messages, {
        "name": name or None, "product_reference": product_ref or None,
        "device": device or None, "issue": issue or None,
    })
    cand_name = _coerce_none(ext.get("name")) or _extract_name(user_message)
    if cand_name and not name:
        name = cand_name
    cand_ref = _coerce_none(ext.get("product_reference"))
    if not cand_ref:
        # Regex fallback (offline): trust a bare code only when we actually asked
        # for the product, else require an explicit "product/reference/model" cue —
        # otherwise a one-word name ("Rachit") would be mistaken for a code.
        cue = re.search(r"(?i)\b(product|reference|model|ref|sku)\b", user_message or "")
        if stage == "ts_collecting_product" or cue:
            cand_ref = _extract_product_ref(user_message)
    if cand_ref:
        product_ref = cand_ref
    cand_dev = _coerce_none(ext.get("device")) or _extract_device(user_message)
    if cand_dev and not device:
        device = cand_dev
    cand_issue = _coerce_none(ext.get("issue"))
    if cand_issue:
        issue = cand_issue
    elif _is_concrete_issue(user_message):
        issue = (user_message or "").strip()
    has_symptom = bool(ext.get("has_symptom")) or _is_concrete_issue(issue) or _is_concrete_issue(user_message)
    declines = bool(ext.get("declines_help"))

    if product_ref and not product_desc:
        product_desc, product_ref = _resolve_product(state, context, product_ref)

    issue_known = has_symptom or bool(issue)

    # Caller explicitly has no technical issue → hand back to the main menu.
    if declines or (
        stage == "ts_confirm_issue" and _is_deny_utterance(user_message)
        and not issue_known
    ):
        who = f", {name}" if name else ""
        reply = (f"No problem{who}. I can list your work orders, look one up, or create "
                 "one — what would you like to do?")
        messages.append({"role": "assistant", "content": reply})
        return {**state, "stage": "intent", "intent": None, "messages": messages,
                "final_answer": reply, "speak": reply, "requires_more_info": True}

    # ---- Field-driven: ask only for what's still genuinely missing ----------
    # 1) Name.
    if not name:
        reply = "Sorry, I didn't catch your name — what should I call you?"
        return _ts_return(state, messages, reply, stage="ts_collecting_name",
                          ts_product_ref=product_ref or None, ts_device=device or None,
                          ts_issue=issue or None)

    # 2) Have a name but no sign of an issue yet → ask once (they can describe it,
    #    give a product reference, or decline).
    if not issue_known and not product_ref and stage != "ts_confirm_issue":
        reply = (f"Nice to meet you, {name}. Are you facing a technical difficulty? "
                 "If so, tell me what's going wrong — and the product reference if you have it.")
        return _ts_return(state, messages, reply, stage="ts_confirm_issue",
                          ts_name=name, ts_device=device or None)

    # 3) Product reference.
    if not product_ref:
        lead = "I'm sorry to hear that. " if (issue_known and stage != "ts_collecting_product") else ""
        reply = (f"{lead}What's the product reference for the device? (for example, BDQ) "
                 "Feel free to describe the issue too.")
        return _ts_return(state, messages, reply, stage="ts_collecting_product",
                          ts_name=name or None, ts_device=device or None, ts_issue=issue or None)

    # 4) Concrete symptom (fold the device question in when the lookup gave us
    #    nothing and the caller hasn't named the device yet).
    if not has_symptom:
        ack = (f"Thanks — that's a {product_desc} (ref {product_ref}). " if product_desc
               else f"Thanks — noted product reference {product_ref}. ")
        dev = product_desc or device
        if dev:
            reply = (f"{ack}What exactly is happening with the {dev}? "
                     "(for example, it won't power on, or it's overheating and shutting down)")
        else:
            reply = (f"{ack}I couldn't pull up details for that reference — what device is this "
                     "and what's going wrong? (for example, 'HP EliteBook laptop — it overheats and freezes')")
        return _ts_return(state, messages, reply, stage="ts_collecting_issue",
                          ts_name=name or None, ts_product_ref=product_ref or None,
                          ts_product_desc=product_desc or None, ts_device=device or None,
                          ts_issue=issue or None)

    # 5) Name + product reference + concrete symptom → troubleshoot.
    return _enter_troubleshooting(
        state, messages, name=name, product_ref=product_ref,
        product_desc=product_desc, device=device, issue=issue, lead="",
    )


def _canonicalize_customer_code(value: str, customer_codes: list) -> str:
    """Snap a spoken/spelled/mis-heard customer code to the closest AUTHORIZED
    code ('del Q X S' / 'BELLQXS' / 'DELLQS' → 'DELLQXS'). Falls back to upper-cased
    input when nothing matches."""
    v = (value or "").strip()
    if not v:
        return v
    matched = _match_customer_from_utterance(f"customer code {v}", customer_codes)
    return matched or v.upper()


_CREATE_FIELD_KEYS = (
    "Customer Code", "Product Reference", "Contact Name", "Contact Phone",
    "Contact Email", "Customer Address", "Customer City", "Customer State",
    "Customer Postal Code", "Site ID", "Customer Call Number",
)


def _create_llm_extract(messages: list, known: dict, customer_codes: list) -> dict:
    """LLM extraction/correction of work-order create fields from natural language,
    mapping a mis-heard customer code to an authorized one. {} when no key/on error."""
    if not os.getenv("OPENAI_API_KEY"):
        return {}
    try:
        from langchain_openai import ChatOpenAI

        model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
        llm = ChatOpenAI(model=model, temperature=0)
        codes = ", ".join(
            (c.get("code") if isinstance(c, dict) else str(c)) for c in (customer_codes or [])
        ) or "none"
        sys = (
            "Extract or CORRECT work-order intake fields from the caller's latest message "
            "and the conversation. Return ONLY JSON (no markdown) with any of these keys, "
            "using null when not mentioned: Customer Code, Product Reference, Contact Name, "
            "Contact Phone, Customer City, Customer State, Customer Postal Code, Site ID.\n"
            f"Customer Code MUST be one of these authorized codes — map any spoken, spelled-out, "
            f"or mis-heard form to the closest one: {codes}.\n"
            "Contact Phone: digits only. Keep prior known values unless the caller corrects them.\n"
            f"Known so far: {json.dumps(known)}"
        )
        res = llm.invoke([{"role": "system", "content": sys}] + messages[-6:])
        data = _parse_json(res.content)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _apply_create_corrections(
    messages: list,
    user_message: str,
    create_fields: dict,
    customer_codes: list,
) -> tuple[dict, bool]:
    """Merge field corrections from a confirm-stage reply into create_fields
    (LLM-first, regex fallback), snapping the customer code to the authorized list.
    Returns (merged_fields, changed) — changed is False when nothing was corrected."""
    updates: dict = {}
    for key, val in (_create_llm_extract(messages, create_fields, customer_codes) or {}).items():
        if key in _CREATE_FIELD_KEYS:
            cv = _coerce_none(val)
            if cv:
                updates[key] = cv
    for key, val in _extract_create_fields_from_text(user_message, customer_codes).items():
        updates.setdefault(key, val)
    # Explicit product-reference correction ("change BBQ to BDQ", "BDQ not BBQ").
    pc = _extract_product_ref_correction(user_message)
    if pc:
        updates["Product Reference"] = pc
    if updates.get("Customer Code"):
        updates["Customer Code"] = _canonicalize_customer_code(updates["Customer Code"], customer_codes)
    else:
        matched = _match_customer_from_utterance(user_message, customer_codes)
        if matched:
            updates["Customer Code"] = matched

    clean = {k: _coerce_none(v) for k, v in updates.items()}
    changed = any(v and v != (create_fields.get(k) or "") for k, v in clean.items())
    merged = dict(create_fields)
    merged.update({k: v for k, v in clean.items() if v})
    return _normalize_create_fields(merged), changed


def converse(state: WWTSState) -> WWTSState:
    stage = state.get("stage") or "greeting"
    intent = state.get("intent")
    context = state.get("context") or {}
    customer_code = context.get("customer_code", "")
    customer_codes = context.get("customer_codes") or []
    wo_number = state.get("wo_number")
    wo_part_line = state.get("wo_part_line")
    search_filters = api._normalize_search_filters(dict(state.get("search_filters") or {}))
    create_fields = _normalize_create_fields(dict(state.get("create_fields") or {}))
    close_fields = api._normalize_close_fields(dict(state.get("close_fields") or {}))
    reopen_reason = (state.get("reopen_reason") or "").strip()
    remark_text = (state.get("remark_text") or "").strip()
    wo_detail = state.get("wo_detail")
    messages = list(state.get("messages") or [])
    user_message = state.get("user_message", "")
    if user_message:
        messages.append({"role": "user", "content": user_message})

    has_customer_code = bool(customer_code) or bool(customer_codes)
    multi_codes = len(customer_codes) > 1

    # Laptop troubleshooting sub-flow (isolated early return). Continue it whenever
    # we're mid-flow; start it fresh only from an idle stage so it can't hijack an
    # in-progress structured flow (create/close/remark/search collection).
    ts_active = intent == "troubleshoot" and stage in _TS_STAGES
    ts_trigger = bool(
        user_message
        and not ts_active
        and stage in ("greeting", "intent", "done")
        and (_is_pure_greeting(user_message) or _detect_troubleshoot_intent(user_message))
    )
    if user_message and (ts_active or ts_trigger):
        handled = _handle_troubleshoot(
            state, messages, user_message, context, fresh=ts_trigger
        )
        if handled is not None:
            return handled
        # Support flow declined this turn (a work-order command) — drop it and
        # let normal routing handle the message.
        state = {**state, "stage": "intent", "intent": None}
        stage = "intent"
        intent = None

    if stage == "collecting_search_criteria" and user_message:
        search_filters = _merge_search_filters(
            search_filters, _extract_search_filters_from_text(user_message)
        )
        matched_customer = _match_customer_from_utterance(user_message, customer_codes)
        if matched_customer:
            search_filters["customer_code"] = matched_customer
        if not search_filters.get("customer_code"):
            if customer_code:
                search_filters["customer_code"] = customer_code
            elif len(customer_codes) == 1:
                c = customer_codes[0]
                search_filters["customer_code"] = c["code"] if isinstance(c, dict) else c
        keyword_status = _detect_wo_status(user_message)
        if keyword_status:
            search_filters["wo_status"] = keyword_status
        keyword_days = _detect_days_back(user_message)
        if keyword_days:
            search_filters["days_back"] = keyword_days
        if not _missing_search_criteria(search_filters, multi_codes):
            summary = _build_search_summary(search_filters)
            messages.append({"role": "assistant", "content": summary})
            return {
                **state,
                "stage": "executing_list",
                "intent": "search_wo",
                "search_filters": search_filters,
                "wo_status": search_filters.get("wo_status", "A"),
                "wo_days_back": search_filters.get("days_back"),
                "messages": messages,
                "final_answer": summary,
                "speak": summary,
                "requires_more_info": False,
            }
        ask = (
            "I need a search criterion — "
            + ", ".join(_missing_search_criteria(search_filters, multi_codes))
            + "."
        )
        messages.append({"role": "assistant", "content": ask})
        return {
            **state,
            "stage": "collecting_search_criteria",
            "intent": "search_wo",
            "search_filters": search_filters,
            "messages": messages,
            "final_answer": ask,
            "speak": ask,
            "requires_more_info": True,
        }

    if stage == "collecting_wo_part_line" and user_message:
        line = _extract_part_line_number(user_message) or wo_part_line
        if line and wo_number:
            msg = f"Looking up part line {line} on work order {wo_number}."
            messages.append({"role": "assistant", "content": msg})
            return {
                **state,
                "stage": "executing_get_part_line",
                "intent": "get_wo_part_line",
                "wo_number": wo_number,
                "wo_part_line": line,
                "messages": messages,
                "final_answer": msg,
                "speak": msg,
                "requires_more_info": False,
            }
        prompt = "Which part line number should I look up on this work order?"
        messages.append({"role": "assistant", "content": prompt})
        return {
            **state,
            "stage": "collecting_wo_part_line",
            "intent": "get_wo_part_line",
            "wo_number": wo_number,
            "messages": messages,
            "final_answer": prompt,
            "speak": prompt,
            "requires_more_info": True,
        }

    if stage == "collecting_wo_number" and (state.get("intent") == "add_wo_remark") and user_message:
        wo_candidate = _extract_wo_number_from_text(user_message or "") or state.get("wo_number")
        if not wo_candidate:
            ask = "What work order number would you like to add a remark to?"
            messages.append({"role": "assistant", "content": ask})
            return {
                **state,
                "stage": "collecting_wo_number",
                "intent": "add_wo_remark",
                "messages": messages,
                "final_answer": ask,
                "speak": ask,
                "requires_more_info": True,
            }
        ask = "What remark should I add to this work order?"
        messages.append({"role": "assistant", "content": ask})
        return {
            **state,
            "stage": "collecting_remark_text",
            "intent": "add_wo_remark",
            "wo_number": wo_candidate,
            "messages": messages,
            "final_answer": ask,
            "speak": ask,
            "requires_more_info": True,
        }

    if stage == "confirming_list" and user_message:
        list_code = state.get("list_customer_code") or ""
        label = list_code
        for c in customer_codes:
            code = c.get("code") if isinstance(c, dict) else c
            if code == list_code:
                label = c.get("name", code) if isinstance(c, dict) else code
                break
        if _is_confirm_utterance(user_message):
            msg = "Let me check your open work orders."
            messages.append({"role": "assistant", "content": msg})
            return {
                **state,
                "stage": "executing_list",
                "intent": "list_wo",
                "list_customer_code": list_code,
                "messages": messages,
                "final_answer": msg,
                "speak": msg,
                "requires_more_info": False,
            }
        if _is_deny_utterance(user_message):
            msg = "Okay. Which customer or task would you like instead?"
            messages.append({"role": "assistant", "content": msg})
            return {
                **state,
                "stage": "intent",
                "intent": None,
                "list_customer_code": None,
                "messages": messages,
                "final_answer": msg,
                "speak": msg,
                "requires_more_info": True,
            }
        msg = f"List open work orders for {label}? Say yes to confirm."
        messages.append({"role": "assistant", "content": msg})
        return {
            **state,
            "stage": "confirming_list",
            "intent": "list_wo",
            "list_customer_code": list_code,
            "messages": messages,
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    if stage == "confirming_create" and user_message:
        summary = _build_create_summary(create_fields)
        if _is_confirm_utterance(user_message):
            confirm_msg = "Creating the work order now."
            messages.append({"role": "assistant", "content": confirm_msg})
            return {
                **state,
                "stage": "executing_create",
                "intent": "create_wo",
                "create_fields": create_fields,
                "messages": messages,
                "final_answer": confirm_msg,
                "speak": confirm_msg,
                "requires_more_info": False,
            }
        # Try corrections FIRST — a reply like "change BBQ to BDQ" or "product BDQ
        # not BBQ" carries field edits even though it also trips the deny keyword
        # ("change"/"not"). Apply them so the caller isn't stuck repeating it.
        corrected, changed = _apply_create_corrections(
            messages, user_message, create_fields, customer_codes
        )
        if changed:
            create_fields = corrected
            missing = _missing_create_fields(create_fields, has_customer_code, multi_codes)
            if missing:
                ask = "Thanks. I still need " + ", ".join(missing) + "."
                messages.append({"role": "assistant", "content": ask})
                return {
                    **state, "stage": "collecting_create", "intent": "create_wo",
                    "create_fields": create_fields, "messages": messages,
                    "final_answer": ask, "speak": ask, "requires_more_info": True,
                }
            summary = _build_create_summary(create_fields)
            prompt = f"{summary} Please say yes to confirm or no to change something."
            messages.append({"role": "assistant", "content": prompt})
            return {
                **state, "stage": "confirming_create", "intent": "create_wo",
                "create_fields": create_fields, "messages": messages,
                "final_answer": prompt, "speak": prompt, "requires_more_info": True,
            }
        if _is_deny_utterance(user_message):
            deny_msg = "Okay, tell me what to change for the new work order."
            messages.append({"role": "assistant", "content": deny_msg})
            return {
                **state,
                "stage": "collecting_create",
                "intent": "create_wo",
                "create_fields": create_fields,
                "messages": messages,
                "final_answer": deny_msg,
                "speak": deny_msg,
                "requires_more_info": True,
            }
        prompt = f"{summary} Please say yes to confirm or no to change something."
        messages.append({"role": "assistant", "content": prompt})
        return {
            **state,
            "stage": "confirming_create",
            "intent": "create_wo",
            "create_fields": create_fields,
            "messages": messages,
            "final_answer": prompt,
            "speak": prompt,
            "requires_more_info": True,
        }

    if stage == "collecting_close_reason" and user_message:
        # Prefer WO already stored; fall back to parsing from the message.
        wo_number = state.get("wo_number") or _extract_wo_number_from_text(user_message or "")
        if not wo_number:
            ask = "What work order number would you like to close?"
            messages.append({"role": "assistant", "content": ask})
            return {
                **state,
                "stage": "collecting_wo_number",
                "intent": "close_wo",
                "close_fields": close_fields,
                "wo_number": None,
                "messages": messages,
                "final_answer": ask,
                "speak": ask,
                "requires_more_info": True,
            }

        extracted_reason = _extract_close_reason_from_text(user_message or "")
        if extracted_reason:
            close_fields["Close Reason"] = extracted_reason
        elif not close_fields.get("Close Reason"):
            # Free-text reason ("the work is completed") — use the whole reply
            # as the reason when it isn't a bare yes/no.
            candidate = (user_message or "").strip().rstrip(".")
            if not _is_deny_utterance(candidate) and len(candidate) >= api._MIN_LIFECYCLE_REASON_LEN:
                close_fields["Close Reason"] = candidate

        missing = api.missing_close_fields(close_fields)
        if missing:
            ask = "What is the reason for closing this work order?"
            messages.append({"role": "assistant", "content": ask})
            return {
                **state,
                "stage": "collecting_close_reason",
                "intent": "close_wo",
                "wo_number": wo_number,
                "close_fields": close_fields,
                "messages": messages,
                "final_answer": ask,
                "speak": ask,
                "requires_more_info": True,
            }

        detail, err = _preflight_for_confirm(
            state,
            intent="close_wo",
            wo_number=wo_number,
            customer_codes=customer_codes,
        )
        if err:
            return {
                **state,
                "stage": "done",
                "intent": "close_wo",
                "wo_number": wo_number,
                "final_answer": err,
                "speak": err,
                "requires_more_info": False,
            }

        summary = _build_close_summary(wo_number, detail, close_fields)
        messages.append({"role": "assistant", "content": summary})
        return {
            **state,
            "stage": "confirming_close",
            "intent": "close_wo",
            "wo_number": wo_number,
            "close_fields": close_fields,
            "wo_detail": detail,
            "messages": messages,
            "final_answer": summary,
            "speak": summary,
            "requires_more_info": True,
        }

    if stage == "confirming_close" and user_message:
        if _is_confirm_utterance(user_message):
            msg = "Closing the work order now."
            messages.append({"role": "assistant", "content": msg})
            return {
                **state,
                "stage": "executing_close",
                "intent": "close_wo",
                "wo_number": state.get("wo_number"),
                "close_fields": close_fields,
                "wo_detail": wo_detail,
                "messages": messages,
                "final_answer": msg,
                "speak": msg,
                "requires_more_info": False,
            }
        if _is_deny_utterance(user_message):
            msg = "Okay. What close reason would you like to use?"
            messages.append({"role": "assistant", "content": msg})
            return {
                **state,
                "stage": "collecting_close_reason",
                "intent": "close_wo",
                "wo_number": state.get("wo_number"),
                "close_fields": close_fields,
                "messages": messages,
                "final_answer": msg,
                "speak": msg,
                "requires_more_info": True,
            }

        # Repeat summary if user message wasn't clearly yes/no.
        wo_number = state.get("wo_number") or ""
        summary = _build_close_summary(wo_number, wo_detail, close_fields)
        messages.append({"role": "assistant", "content": summary})
        return {
            **state,
            "stage": "confirming_close",
            "intent": "close_wo",
            "wo_number": state.get("wo_number"),
            "close_fields": close_fields,
            "wo_detail": wo_detail,
            "messages": messages,
            "final_answer": summary,
            "speak": summary,
            "requires_more_info": True,
        }

    if stage == "collecting_reopen_reason" and user_message:
        wo_number = state.get("wo_number") or _extract_wo_number_from_text(user_message or "")
        if not wo_number:
            ask = "What work order number would you like to reopen?"
            messages.append({"role": "assistant", "content": ask})
            return {
                **state,
                "stage": "collecting_wo_number",
                "intent": "reopen_wo",
                "reopen_reason": reopen_reason,
                "wo_number": None,
                "messages": messages,
                "final_answer": ask,
                "speak": ask,
                "requires_more_info": True,
            }

        extracted_reason = _extract_reopen_reason_from_text(user_message or "")
        if extracted_reason:
            reopen_reason = extracted_reason
        elif len(reopen_reason) < api._MIN_LIFECYCLE_REASON_LEN:
            candidate = (user_message or "").strip().rstrip(".")
            if not _is_deny_utterance(candidate) and len(candidate) >= api._MIN_LIFECYCLE_REASON_LEN:
                reopen_reason = candidate

        if len(reopen_reason) < api._MIN_LIFECYCLE_REASON_LEN:
            ask = "What is the reason for reopening this work order?"
            messages.append({"role": "assistant", "content": ask})
            return {
                **state,
                "stage": "collecting_reopen_reason",
                "intent": "reopen_wo",
                "wo_number": wo_number,
                "reopen_reason": reopen_reason,
                "messages": messages,
                "final_answer": ask,
                "speak": ask,
                "requires_more_info": True,
            }

        detail, err = _preflight_for_confirm(
            state,
            intent="reopen_wo",
            wo_number=wo_number,
            customer_codes=customer_codes,
        )
        if err:
            return {
                **state,
                "stage": "done",
                "intent": "reopen_wo",
                "wo_number": wo_number,
                "final_answer": err,
                "speak": err,
                "requires_more_info": False,
            }

        summary = _build_reopen_summary(wo_number, detail, reopen_reason)
        messages.append({"role": "assistant", "content": summary})
        return {
            **state,
            "stage": "confirming_reopen",
            "intent": "reopen_wo",
            "wo_number": wo_number,
            "reopen_reason": reopen_reason,
            "wo_detail": detail,
            "messages": messages,
            "final_answer": summary,
            "speak": summary,
            "requires_more_info": True,
        }

    if stage == "confirming_reopen" and user_message:
        if _is_confirm_utterance(user_message):
            msg = "Reopening the work order now."
            messages.append({"role": "assistant", "content": msg})
            return {
                **state,
                "stage": "executing_reopen",
                "intent": "reopen_wo",
                "wo_number": state.get("wo_number"),
                "reopen_reason": reopen_reason,
                "wo_detail": wo_detail,
                "messages": messages,
                "final_answer": msg,
                "speak": msg,
                "requires_more_info": False,
            }
        if _is_deny_utterance(user_message):
            msg = "Okay. What reopen reason would you like to use?"
            messages.append({"role": "assistant", "content": msg})
            return {
                **state,
                "stage": "collecting_reopen_reason",
                "intent": "reopen_wo",
                "wo_number": state.get("wo_number"),
                "reopen_reason": reopen_reason,
                "messages": messages,
                "final_answer": msg,
                "speak": msg,
                "requires_more_info": True,
            }

        wo_number = state.get("wo_number") or ""
        summary = _build_reopen_summary(wo_number, wo_detail, reopen_reason)
        messages.append({"role": "assistant", "content": summary})
        return {
            **state,
            "stage": "confirming_reopen",
            "intent": "reopen_wo",
            "wo_number": state.get("wo_number"),
            "reopen_reason": reopen_reason,
            "wo_detail": wo_detail,
            "messages": messages,
            "final_answer": summary,
            "speak": summary,
            "requires_more_info": True,
        }

    if stage == "collecting_remark_text" and user_message:
        wo_number = state.get("wo_number") or _extract_wo_number_from_text(user_message or "")
        if not wo_number:
            ask = "What work order number would you like to add a remark to?"
            messages.append({"role": "assistant", "content": ask})
            return {
                **state,
                "stage": "collecting_wo_number",
                "intent": "add_wo_remark",
                "remark_text": remark_text,
                "wo_number": None,
                "messages": messages,
                "final_answer": ask,
                "speak": ask,
                "requires_more_info": True,
            }

        # We explicitly asked "what remark?" — the reply IS the remark. Use the
        # extracted form if a pattern matched, else the whole reply, overwriting
        # any stale value carried over from an earlier turn.
        extracted_remark = _extract_remark_text_from_text(user_message or "")
        if extracted_remark:
            remark_text = extracted_remark
        else:
            candidate = (user_message or "").strip()
            if candidate and not _is_confirm_utterance(candidate) and not _is_deny_utterance(candidate):
                remark_text = candidate

        if len((remark_text or "").strip()) < api._MIN_LIFECYCLE_REASON_LEN:
            ask = "What remark should I add to this work order?"
            messages.append({"role": "assistant", "content": ask})
            return {
                **state,
                "stage": "collecting_remark_text",
                "intent": "add_wo_remark",
                "wo_number": wo_number,
                "remark_text": remark_text,
                "messages": messages,
                "final_answer": ask,
                "speak": ask,
                "requires_more_info": True,
            }

        pre = api.get_workorder_full(user_id=state.get("user_id", ""), session=context.get("wwts_session"), wo_number=wo_number, customer_codes=customer_codes)
        if not pre.get("success"):
            err = _friendly_err(pre.get("error")) or f"Work order {wo_number} could not be validated."
            return {
                **state,
                "stage": "done",
                "intent": "add_wo_remark",
                "wo_number": wo_number,
                "remark_text": remark_text,
                "final_answer": err,
                "speak": err,
                "requires_more_info": False,
            }

        detail = pre.get("detail") or {}
        summary = _build_remark_summary(wo_number, detail, remark_text)
        messages.append({"role": "assistant", "content": summary})
        return {
            **state,
            "stage": "confirming_remark",
            "intent": "add_wo_remark",
            "wo_number": wo_number,
            "remark_text": remark_text,
            "wo_detail": detail,
            "messages": messages,
            "final_answer": summary,
            "speak": summary,
            "requires_more_info": True,
        }

    if stage == "confirming_remark" and user_message:
        if _is_confirm_utterance(user_message):
            msg = "Adding the remark now."
            messages.append({"role": "assistant", "content": msg})
            return {
                **state,
                "stage": "executing_remark",
                "intent": "add_wo_remark",
                "wo_number": state.get("wo_number"),
                "remark_text": remark_text,
                "wo_detail": wo_detail,
                "messages": messages,
                "final_answer": msg,
                "speak": msg,
                "requires_more_info": False,
            }
        if _is_deny_utterance(user_message):
            msg = "Okay. What remark text would you like to use?"
            messages.append({"role": "assistant", "content": msg})
            return {
                **state,
                "stage": "collecting_remark_text",
                "intent": "add_wo_remark",
                "wo_number": state.get("wo_number"),
                "remark_text": remark_text,
                "messages": messages,
                "final_answer": msg,
                "speak": msg,
                "requires_more_info": True,
            }

        wo_number = state.get("wo_number") or ""
        summary = _build_remark_summary(wo_number, wo_detail, remark_text)
        messages.append({"role": "assistant", "content": summary})
        return {
            **state,
            "stage": "confirming_remark",
            "intent": "add_wo_remark",
            "wo_number": state.get("wo_number"),
            "remark_text": remark_text,
            "wo_detail": wo_detail,
            "messages": messages,
            "final_answer": summary,
            "speak": summary,
            "requires_more_info": True,
        }

    # Collapse "done" back to "greeting" only when message is a pure greeting
    if stage == "done" and user_message:
        stage = "intent"

    missing = _missing_create_fields(create_fields, has_customer_code, multi_codes)
    missing_search = _missing_search_criteria(search_filters, multi_codes)

    if not os.getenv("OPENAI_API_KEY"):
        return _fallback(
            state, stage, messages, user_message, search_filters=search_filters
        )

    from langchain_openai import ChatOpenAI

    model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")

    # Build codes display for the prompt
    if customer_codes:
        codes_entries = []
        for c in customer_codes:
            if isinstance(c, dict):
                code = c.get("code", "")
                name = c.get("name", "")
                codes_entries.append(f"{code} ({name})" if name else code)
            else:
                codes_entries.append(c)
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
        search_filters=_safe(json.dumps(search_filters) if search_filters else "{}"),
        missing_search=_safe(", ".join(missing_search) if missing_search else "none"),
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
        return _fallback(
            state, stage, messages, user_message, search_filters=search_filters
        )

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
    keyword_routed = _keyword_stage(user_message) if user_message else None
    wo_get_focus = state.get("wo_get_focus")
    in_create_flow = stage in ("collecting_create", "confirming_create") or intent == "create_wo"
    # "find the remarks/parts/labor on this work order" is a focused read of a
    # known WO, NOT a search — don't let the greedy "find…order" search heuristic
    # hijack it into the search-criteria loop.
    _focus_on_known_wo = bool(
        user_message
        and (new_wo_number or wo_number)
        and (_detect_focused_read_intent(user_message) or _detect_get_focus(user_message))
    )
    if user_message and (not in_create_flow) and (not _focus_on_known_wo) and _is_search_request(user_message):
        search_filters = _merge_search_filters(
            search_filters, _extract_search_filters_from_text(user_message)
        )
        matched_customer = _match_customer_from_utterance(user_message, customer_codes)
        if matched_customer:
            search_filters["customer_code"] = matched_customer
        new_intent = "search_wo"
        if keyword_status:
            search_filters["wo_status"] = keyword_status
        if keyword_days:
            search_filters["days_back"] = keyword_days
        if not search_filters.get("customer_code"):
            if customer_code:
                search_filters["customer_code"] = customer_code
            elif len(customer_codes) == 1:
                c = customer_codes[0]
                search_filters["customer_code"] = c["code"] if isinstance(c, dict) else c
        if api._has_search_criteria(search_filters, multi_codes):
            new_stage = "executing_list"
            response_text = _build_search_summary(search_filters)
            speak_text = response_text
        else:
            new_stage = "collecting_search_criteria"

    # Deterministic routing guardrail: explicit create/get utterances should not be
    # overridden by an LLM hallucinated list/search stage.
    if keyword_routed == "collecting_create":
        new_intent = "create_wo"
        new_stage = "collecting_create"
        response_text = "I can help create a work order. What is the product reference?"
        speak_text = response_text
    elif keyword_routed == "collecting_wo_number" and new_intent not in (
        "create_wo", "close_wo", "reopen_wo", "add_wo_remark"
    ):
        new_intent = "get_wo"
        known_wo = new_wo_number or wo_number
        if known_wo:
            # A WO is already in context (e.g. just created/looked up) — answer
            # about it instead of re-asking for the number.
            new_wo_number = known_wo
            new_stage = "executing_get"
            response_text = f"Let me pull up work order {known_wo}."
        else:
            new_stage = "collecting_wo_number"
            response_text = "What work order number would you like to look up?"
        speak_text = response_text

    focused_intent = _detect_focused_read_intent(user_message) if user_message else None
    if focused_intent:
        new_intent = focused_intent
        new_wo_number = new_wo_number or wo_number
        new_stage, new_wo_number, new_part_line = _route_focused_read(
            focused_intent,
            wo_number=new_wo_number,
            wo_part_line=wo_part_line,
            user_message=user_message,
            stage=stage,
        )
        wo_part_line = new_part_line
    else:
        detected_focus = _detect_get_focus(user_message) if user_message else None
        if detected_focus:
            wo_get_focus = detected_focus
            new_wo_number = new_wo_number or wo_number
            if new_wo_number and new_stage not in (
                "executing_create",
                "collecting_create",
                "confirming_create",
            ):
                new_stage = "executing_get"
                # Claim get_wo outright so the later search_wo re-routing can't
                # bounce a focused read back to the search-criteria loop.
                new_intent = "get_wo"

    extracted_line = extracted.get("wo_part_line")
    if extracted_line is not None:
        try:
            wo_part_line = int(extracted_line)
        except (TypeError, ValueError):
            pass
    if wo_part_line and new_intent == "get_wo_part_line" and new_wo_number:
        if new_stage in ("collecting_wo_part_line", "collecting_wo_number"):
            new_stage = "executing_get_part_line"

    # Fields that must not be silently overwritten — only update if currently empty.
    # Prevents possessive phrases ("phone for Achyut") from clobbering explicit earlier
    # values. (Product Reference is intentionally NOT here: blocking it stopped real
    # corrections; mis-hears are handled by snapping to the customer's product list.)
    _NO_OVERWRITE = {"Contact Name"}

    raw_create = extracted.get("create_fields") or {}
    for key, val in raw_create.items():
        coerced = _coerce_none(val)
        if coerced:
            if key in _NO_OVERWRITE and create_fields.get(key):
                continue  # already set — don't overwrite from incidental mention
            create_fields[key] = coerced
    create_fields = _normalize_create_fields(create_fields)

    raw_search = extracted.get("search_filters") or {}
    if isinstance(raw_search, dict):
        for key, val in raw_search.items():
            coerced = _coerce_none(val)
            if coerced:
                raw_search[key] = coerced
        search_filters = _merge_search_filters(search_filters, raw_search)
    if new_intent == "create_wo" or stage in ("collecting_create", "confirming_create"):
        create_fields = _promote_create_customer_code(
            create_fields,
            search_filters,
            customer_codes,
        )
        if create_fields.get("Customer Code"):
            create_fields["Customer Code"] = _canonicalize_customer_code(
                create_fields["Customer Code"], customer_codes
            )

    if isinstance(extracted.get("close_fields"), dict):
        close_fields = _merge_close_fields(close_fields, extracted.get("close_fields") or {})
    extracted_reopen_reason = _coerce_none(extracted.get("reopen_reason"))
    if extracted_reopen_reason:
        reopen_reason = extracted_reopen_reason
    extracted_remark_text = _coerce_none(extracted.get("remark_text"))
    if extracted_remark_text:
        remark_text = extracted_remark_text

    # Auto-populate Customer Code only when the session has exactly one code
    if not create_fields.get("Customer Code"):
        if customer_code:
            create_fields["Customer Code"] = customer_code
        elif len(customer_codes) == 1:
            c = customer_codes[0]
            create_fields["Customer Code"] = c["code"] if isinstance(c, dict) else c
        # If multi_codes: leave empty — user must choose

    # Lookback change on an existing search/list ("increase the lookback to 8
    # months") — keep the prior filters, just widen the window, and re-run.
    if (
        user_message
        and keyword_days
        and not in_create_flow
        and new_stage not in ("collecting_create", "confirming_create")
        and (intent in ("search_wo", "list_wo") or api._has_search_criteria(search_filters, multi_codes))
    ):
        new_days_back = keyword_days
        if intent == "search_wo" or api._has_search_criteria(search_filters, multi_codes):
            search_filters["days_back"] = keyword_days
            new_intent = "search_wo"
        else:
            new_intent = "list_wo"
        new_stage = "executing_list"

    if new_intent == "search_wo":
        if api._has_search_criteria(search_filters, multi_codes):
            new_stage = "executing_list"
        else:
            new_stage = "collecting_search_criteria"

    if new_stage == "executing_list" and new_intent == "search_wo":
        if _missing_search_criteria(search_filters, multi_codes):
            new_stage = "collecting_search_criteria"
        else:
            response_text = _build_search_summary(search_filters)
            speak_text = response_text

    if new_stage == "executing_list" and new_intent != "search_wo":
        search_filters = {}

    # Safety: require confirmation before create executes
    if new_stage == "executing_create":
        if _missing_create_fields(create_fields, has_customer_code, multi_codes):
            new_stage = "collecting_create"
        else:
            new_stage = "confirming_create"
            response_text = _build_create_summary(create_fields)
            speak_text = response_text

    if new_intent == "create_wo" and new_stage == "collecting_create":
        missing_create = _missing_create_fields(create_fields, has_customer_code, multi_codes)
        if missing_create:
            response_text = "I still need " + ", ".join(missing_create) + "."
            speak_text = response_text
        else:
            new_stage = "confirming_create"
            response_text = _build_create_summary(create_fields)
            speak_text = response_text

    if new_stage == "confirming_create" and not _missing_create_fields(
        create_fields, has_customer_code, multi_codes
    ):
        response_text = _build_create_summary(create_fields)
        speak_text = response_text

    lifecycle_intent = _detect_lifecycle_intent(user_message or "") if user_message else None
    if lifecycle_intent == "close_wo":
        new_intent = "close_wo"
        new_stage, new_wo_number, close_fields = _route_close_flow(
            wo_number=new_wo_number,
            close_fields=close_fields,
            user_message=user_message,
        )
        if new_stage == "collecting_wo_number":
            response_text = "What work order number would you like to close?"
            speak_text = response_text
        elif new_stage == "collecting_close_reason":
            response_text = "What is the reason for closing this work order?"
            speak_text = response_text
        elif new_stage == "confirming_close" and new_wo_number:
            detail, err = _preflight_for_confirm(
                state,
                intent="close_wo",
                wo_number=new_wo_number,
                customer_codes=customer_codes,
            )
            if err:
                new_stage = "done"
                response_text = err
                speak_text = err
            else:
                wo_detail = detail
                response_text = _build_close_summary(new_wo_number, detail, close_fields)
                speak_text = response_text

    elif lifecycle_intent == "reopen_wo":
        new_intent = "reopen_wo"
        new_stage, new_wo_number, reopen_reason = _route_reopen_flow(
            wo_number=new_wo_number,
            reopen_reason=reopen_reason,
            user_message=user_message,
        )
        if new_stage == "collecting_wo_number":
            response_text = "What work order number would you like to reopen?"
            speak_text = response_text
        elif new_stage == "collecting_reopen_reason":
            response_text = "What is the reason for reopening this work order?"
            speak_text = response_text
        elif new_stage == "confirming_reopen" and new_wo_number:
            detail, err = _preflight_for_confirm(
                state,
                intent="reopen_wo",
                wo_number=new_wo_number,
                customer_codes=customer_codes,
            )
            if err:
                new_stage = "done"
                response_text = err
                speak_text = err
            else:
                wo_detail = detail
                response_text = _build_reopen_summary(new_wo_number, detail, reopen_reason)
                speak_text = response_text
    elif _detect_remark_intent(user_message or ""):
        new_intent = "add_wo_remark"
        new_stage, new_wo_number, remark_text = _route_remark_flow(
            wo_number=new_wo_number,
            remark_text=remark_text,
            user_message=user_message,
        )
        if new_stage == "collecting_wo_number":
            response_text = "What work order number would you like to add a remark to?"
            speak_text = response_text
        elif new_stage == "collecting_remark_text":
            response_text = "What remark should I add to this work order?"
            speak_text = response_text
        elif new_stage == "confirming_remark" and new_wo_number:
            pre = api.get_workorder_full(
                user_id=state.get("user_id", ""),
                session=context.get("wwts_session"),
                wo_number=new_wo_number,
                customer_codes=customer_codes,
            )
            if not pre.get("success"):
                new_stage = "done"
                response_text = _friendly_err(pre.get("error")) or f"Work order {new_wo_number} could not be validated."
                speak_text = response_text
            else:
                wo_detail = pre.get("detail")
                response_text = _build_remark_summary(new_wo_number, wo_detail, remark_text)
                speak_text = response_text

    # Sticky create flow: don't let the LLM silently drop an in-progress create
    # back to the idle menu. Only a real switch (another concrete intent) or an
    # explicit cancel — both handled above — should leave the create flow.
    _was_creating = intent == "create_wo" or stage in ("collecting_create", "confirming_create")
    _switched_intent = new_intent not in (None, "create_wo") or bool(
        lifecycle_intent or focused_intent
    )
    if _was_creating and not _switched_intent and new_stage in ("intent", "greeting"):
        new_intent = "create_wo"
        _still_missing = _missing_create_fields(create_fields, has_customer_code, multi_codes)
        if _still_missing:
            new_stage = "collecting_create"
            response_text = "I still need " + ", ".join(_still_missing) + "."
        else:
            new_stage = "confirming_create"
            response_text = _build_create_summary(create_fields)
        speak_text = response_text

    messages.append({"role": "assistant", "content": response_text})

    return {
        **state,
        "stage": new_stage,
        "intent": new_intent,
        "wo_number": new_wo_number,
        "wo_status": new_wo_status,
        "wo_days_back": new_days_back,
        "wo_get_focus": wo_get_focus,
        "wo_part_line": wo_part_line,
        "search_filters": search_filters,
        "create_fields": create_fields,
        "close_fields": close_fields,
        "reopen_reason": reopen_reason,
        "remark_text": remark_text,
        "wo_detail": wo_detail,
        "messages": messages,
        "final_answer": response_text,
        "speak": speak_text,
        "requires_more_info": new_stage not in _EXECUTING_STAGES
        and new_stage != "done",
    }


_LIST_KW  = {"list", "show", "how many", "count", "open", "pending", "orders",
             "work orders", "any orders", "current", "in progress", "active"}
_GET_KW   = {
    "details", "status", "look up", "get wo", "history", "updates", "specific",
    "parts", "part ", "shipped", "technician", "tech on", "labor", "csr",
}
_CREATE_KW = {"create", "open a", "new work order", "file", "submit"}


def _keyword_stage(text: str) -> str | None:
    lower = text.lower()
    if any(k in lower for k in _CREATE_KW):
        return "collecting_create"
    lifecycle = _detect_lifecycle_intent(text)
    if lifecycle == "close_wo":
        return "collecting_close_reason"
    if lifecycle == "reopen_wo":
        return "collecting_reopen_reason"
    if _detect_remark_intent(text):
        return "collecting_remark_text"
    focused = _detect_focused_read_intent(text)
    if focused:
        stage, _, _ = _route_focused_read(
            focused, wo_number=None, wo_part_line=None, user_message=text, stage="intent"
        )
        return stage
    if any(k in lower for k in _GET_KW):
        return "collecting_wo_number"
    if _is_search_request(text):
        return "collecting_search_criteria"
    if any(k in lower for k in _LIST_KW):
        return "executing_list"
    return None


def _match_customer_from_utterance(text: str, customer_codes: list) -> str | None:
    """Resolve a customer code from spoken name/code in the utterance."""
    lower = text.lower()
    compact = re.sub(r"[^a-z0-9]", "", lower)
    tokens = [re.sub(r"[^a-z0-9]", "", t) for t in lower.split()]
    tokens = [t for t in tokens if t]
    cust_match = re.search(r"(?:customer\s+(?:id|code)\s*(?:is|=|:)?\s*)([a-z0-9\-\s]+)", lower)
    if cust_match:
        phrase = re.sub(r"[^a-z0-9]", "", cust_match.group(1))
        if phrase:
            tokens.append(phrase)

    def _distance(a: str, b: str) -> int:
        if a == b:
            return 0
        if not a:
            return len(b)
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, start=1):
            curr = [i]
            for j, cb in enumerate(b, start=1):
                cost = 0 if ca == cb else 1
                curr.append(min(
                    prev[j] + 1,      # deletion
                    curr[j - 1] + 1,  # insertion
                    prev[j - 1] + cost,  # substitution
                ))
            prev = curr
        return prev[-1]

    def _variants(value: str) -> set[str]:
        base = re.sub(r"[^a-z0-9]", "", (value or "").lower())
        variants = {base}
        # Common STT swaps around Q/X/P/S in customer codes (e.g., XQS/QXS/XPS).
        if "q" in base:
            variants.add(base.replace("q", "x"))
            variants.add(base.replace("q", "p"))
        if "x" in base:
            variants.add(base.replace("x", "q"))
        return {v for v in variants if v}

    for c in customer_codes:
        code = (c.get("code") if isinstance(c, dict) else str(c)).strip()
        name = (c.get("name", "") if isinstance(c, dict) else "").strip()
        if code and code.lower() in lower:
            return code
        if name and name.lower() in lower:
            return code
        code_variants = _variants(code)
        name_variants = _variants(name)
        if any(v in compact for v in code_variants | name_variants):
            return code
        for candidate in code_variants | name_variants:
            if not candidate or len(candidate) < 5:
                continue
            for token in tokens:
                if len(token) >= 5 and _distance(token, candidate) <= 2:
                    return code
    match = re.search(r"\bfor\s+(.+?)(?:[.?!]|$)", lower)
    if match:
        phrase = match.group(1).strip()
        for c in customer_codes:
            code = (c.get("code") if isinstance(c, dict) else str(c)).strip()
            name = (c.get("name", "") if isinstance(c, dict) else "").strip()
            if phrase == name.lower() or phrase == code.lower():
                return code
            if name and phrase in name.lower():
                return code
    return None


def _is_list_for_customer_request(text: str, customer_codes: list) -> str | None:
    """When user says e.g. 'do it for Dell QXS', return matched customer code."""
    lower = text.lower()
    if "for " not in lower:
        return None
    if not any(k in lower for k in ("do it", "list", "show", "count", "how many")):
        return None
    return _match_customer_from_utterance(text, customer_codes)


def _extract_create_fields_from_text(text: str, customer_codes: list) -> dict:
    """Heuristic create-field extraction used by fallback (no LLM path)."""
    found: dict = {}
    lower = (text or "").lower()

    code = _match_customer_from_utterance(text, customer_codes)
    if code:
        found["Customer Code"] = code

    site = re.search(r"\bsite\s*id\s*(?:is|=|:)?\s*([A-Za-z0-9\-]+)\b", text, re.IGNORECASE)
    if site:
        found["Site ID"] = site.group(1).strip().upper()

    product = re.search(r"\bproduct\s+reference\s*(?:is|=|:)?\s*([A-Za-z0-9\-]+)\b", text, re.IGNORECASE)
    if product:
        found["Product Reference"] = product.group(1).strip().upper()

    name = re.search(
        r"\bcontact\s+name\s*(?:is|=|:)?\s*([A-Za-z][A-Za-z .'-]{1,80}?)(?=\s*(?:[.,]|(?:and\s+)?(?:the\s+)?phone|(?:and\s+)?(?:the\s+)?address|$))",
        text,
        re.IGNORECASE,
    )
    if name:
        found["Contact Name"] = name.group(1).strip().rstrip(".,")

    phone = re.search(r"\b(?:contact\s+phone(?:\s+number)?\s*(?:is|=|:)?\s*)?(\+?\d[\d\s\-()]{7,}\d)\b", text, re.IGNORECASE)
    if phone:
        found["Contact Phone"] = re.sub(r"[^\d+]", "", phone.group(1))
    if "Contact Name" not in found:
        name_phone = re.search(
            r"^\s*([A-Za-z][A-Za-z .'-]{1,80})\s*,\s*(\+?\d[\d\s\-()]{7,}\d)\s*$",
            text,
            re.IGNORECASE,
        )
        if name_phone:
            found["Contact Name"] = name_phone.group(1).strip().rstrip(".,")
            found["Contact Phone"] = re.sub(r"[^\d+]", "", name_phone.group(2))

    loc = re.search(
        r"\b([A-Za-z][A-Za-z .'-]{1,40})\s*,\s*([A-Za-z][A-Za-z .'-]{1,30})\s+(\d{5}(?:-\d{4})?)\b",
        text,
    )
    if loc:
        city = loc.group(1).strip()
        city = re.sub(
            r"^(?:and\s+)?(?:the\s+)?(?:address|location)\s+(?:is\s+)?",
            "",
            city,
            flags=re.IGNORECASE,
        ).strip()
        found["Customer City"] = city
        found["Customer State"] = loc.group(2).strip()
        found["Customer Postal Code"] = loc.group(3).strip()

    # Short utterance pattern like: "BDQ and Rachit Gandhi"
    if "Product Reference" not in found and "contact" not in lower:
        short = re.search(
            r"\b([A-Za-z0-9\-]{2,20})\s+(?:and|,)\s+([A-Za-z][A-Za-z .'-]{1,80})\b",
            text,
            re.IGNORECASE,
        )
        if short:
            found["Product Reference"] = short.group(1).strip().upper()
            if "Contact Name" not in found:
                found["Contact Name"] = short.group(2).strip().rstrip(".,")

    return found


def _promote_create_customer_code(
    create_fields: dict,
    search_filters: dict,
    customer_codes: list,
) -> dict:
    """LLM sometimes places "customer code" in search_filters during create flow."""
    if create_fields.get("Customer Code") or not search_filters.get("customer_code"):
        return create_fields
    matched = _match_customer_from_utterance(
        f"customer code {search_filters['customer_code']}",
        customer_codes,
    )
    create_fields["Customer Code"] = matched or str(search_filters["customer_code"]).strip().upper()
    return create_fields


def _fallback(
    state: WWTSState,
    stage: str,
    messages: list,
    user_message: str = "",
    search_filters: dict | None = None,
) -> WWTSState:
    new_intent = state.get("intent")
    sf = api._normalize_search_filters(search_filters or state.get("search_filters") or {})
    create_fields = _normalize_create_fields(dict(state.get("create_fields") or {}))

    if _is_pure_greeting(user_message):
        msg = "Hello! I can list your work orders, look up a specific WO, or create a new one. What do you need?"
        new_stage = "intent"
    else:
        context = state.get("context") or {}
        customer_codes = context.get("customer_codes") or []
        multi_codes = len(customer_codes) > 1
        if user_message:
            create_fields.update(_extract_create_fields_from_text(user_message, customer_codes))
            create_fields = _normalize_create_fields(create_fields)
        if user_message:
            sf = _merge_search_filters(sf, _extract_search_filters_from_text(user_message))
        if state.get("intent") == "create_wo" or stage in ("collecting_create", "confirming_create"):
            create_fields = _promote_create_customer_code(create_fields, sf, customer_codes)
        # Keyword-based routing so the agent progresses even without LLM
        new_stage = stage
        routed = _keyword_stage(user_message) if user_message else None
        list_customer = _is_list_for_customer_request(user_message, customer_codes)
        if list_customer and stage in ("intent", "greeting", "done"):
            new_intent = "list_wo"
            new_stage = "confirming_list"
            label = list_customer
            for c in customer_codes:
                code = c.get("code") if isinstance(c, dict) else c
                if code == list_customer:
                    label = c.get("name", code) if isinstance(c, dict) else code
                    break
            msg = f"List open work orders for {label}? Say yes to confirm."
            messages.append({"role": "assistant", "content": msg})
            return {
                **state,
                "stage": new_stage,
                "intent": new_intent,
                "list_customer_code": list_customer,
                "messages": messages,
                "final_answer": msg,
                "speak": msg,
                "requires_more_info": True,
            }
        # Lookback change on an existing search/list ("increase the lookback to
        # 8 months") — keep prior filters, widen the window, and re-run.
        fb_days = _detect_days_back(user_message or "") if user_message else None
        prior_intent = state.get("intent")
        if (
            fb_days
            and stage not in ("collecting_create", "confirming_create")
            and prior_intent != "create_wo"
            and (prior_intent in ("search_wo", "list_wo") or api._has_search_criteria(sf, multi_codes))
        ):
            if prior_intent == "search_wo" or api._has_search_criteria(sf, multi_codes):
                sf["days_back"] = fb_days
                new_intent = "search_wo"
                msg = _build_search_summary(sf)
            else:
                new_intent = "list_wo"
                msg = "Let me widen the lookback and check again."
            messages.append({"role": "assistant", "content": msg})
            return {
                **state,
                "stage": "executing_list",
                "intent": new_intent,
                "search_filters": sf,
                "wo_days_back": fb_days,
                "wo_status": state.get("wo_status") or "O",
                "messages": messages,
                "final_answer": msg,
                "speak": msg,
                "requires_more_info": False,
            }
        lifecycle_intent = _detect_lifecycle_intent(user_message or "")
        if lifecycle_intent == "close_wo":
            wo_number = state.get("wo_number") or _extract_wo_number_from_text(user_message or "")
            close_fields = api._normalize_close_fields(dict(state.get("close_fields") or {}))
            extracted_reason = _extract_close_reason_from_text(user_message or "")
            if extracted_reason:
                close_fields["Close Reason"] = extracted_reason

            if not wo_number:
                msg = "What work order number would you like to close?"
                messages.append({"role": "assistant", "content": msg})
                return {
                    **state,
                    "stage": "collecting_wo_number",
                    "intent": "close_wo",
                    "wo_number": None,
                    "close_fields": close_fields,
                    "messages": messages,
                    "final_answer": msg,
                    "speak": msg,
                    "requires_more_info": True,
                }

            missing = api.missing_close_fields(close_fields)
            if missing:
                msg = "What is the reason for closing this work order?"
                messages.append({"role": "assistant", "content": msg})
                return {
                    **state,
                    "stage": "collecting_close_reason",
                    "intent": "close_wo",
                    "wo_number": wo_number,
                    "close_fields": close_fields,
                    "messages": messages,
                    "final_answer": msg,
                    "speak": msg,
                    "requires_more_info": True,
                }

            detail, err = _preflight_for_confirm(
                state,
                intent="close_wo",
                wo_number=wo_number,
                customer_codes=customer_codes,
            )
            if err:
                msg = err
                messages.append({"role": "assistant", "content": msg})
                return {
                    **state,
                    "stage": "done",
                    "intent": "close_wo",
                    "wo_number": wo_number,
                    "final_answer": msg,
                    "speak": msg,
                    "requires_more_info": False,
                }

            summary = _build_close_summary(wo_number, detail, close_fields)
            messages.append({"role": "assistant", "content": summary})
            return {
                **state,
                "stage": "confirming_close",
                "intent": "close_wo",
                "wo_number": wo_number,
                "close_fields": close_fields,
                "wo_detail": detail,
                "messages": messages,
                "final_answer": summary,
                "speak": summary,
                "requires_more_info": True,
            }

        if lifecycle_intent == "reopen_wo":
            wo_number = state.get("wo_number") or _extract_wo_number_from_text(user_message or "")
            reopen_reason = (state.get("reopen_reason") or "").strip()
            extracted_reason = _extract_reopen_reason_from_text(user_message or "")
            if extracted_reason:
                reopen_reason = extracted_reason

            if not wo_number:
                msg = "What work order number would you like to reopen?"
                messages.append({"role": "assistant", "content": msg})
                return {
                    **state,
                    "stage": "collecting_wo_number",
                    "intent": "reopen_wo",
                    "wo_number": None,
                    "reopen_reason": reopen_reason,
                    "messages": messages,
                    "final_answer": msg,
                    "speak": msg,
                    "requires_more_info": True,
                }

            if len(reopen_reason) < api._MIN_LIFECYCLE_REASON_LEN:
                msg = "What is the reason for reopening this work order?"
                messages.append({"role": "assistant", "content": msg})
                return {
                    **state,
                    "stage": "collecting_reopen_reason",
                    "intent": "reopen_wo",
                    "wo_number": wo_number,
                    "reopen_reason": reopen_reason,
                    "messages": messages,
                    "final_answer": msg,
                    "speak": msg,
                    "requires_more_info": True,
                }

            detail, err = _preflight_for_confirm(
                state,
                intent="reopen_wo",
                wo_number=wo_number,
                customer_codes=customer_codes,
            )
            if err:
                msg = err
                messages.append({"role": "assistant", "content": msg})
                return {
                    **state,
                    "stage": "done",
                    "intent": "reopen_wo",
                    "wo_number": wo_number,
                    "final_answer": msg,
                    "speak": msg,
                    "requires_more_info": False,
                }

            summary = _build_reopen_summary(wo_number, detail, reopen_reason)
            messages.append({"role": "assistant", "content": summary})
            return {
                **state,
                "stage": "confirming_reopen",
                "intent": "reopen_wo",
                "wo_number": wo_number,
                "reopen_reason": reopen_reason,
                "wo_detail": detail,
                "messages": messages,
                "final_answer": summary,
                "speak": summary,
                "requires_more_info": True,
            }
        if _detect_remark_intent(user_message or ""):
            wo_number = state.get("wo_number") or _extract_wo_number_from_text(user_message or "")
            remark_text = (state.get("remark_text") or "").strip()
            extracted_remark = _extract_remark_text_from_text(user_message or "")
            if extracted_remark:
                remark_text = extracted_remark
            elif len(remark_text) < api._MIN_LIFECYCLE_REASON_LEN:
                remark_text = (user_message or "").strip()

            if not wo_number:
                msg = "What work order number would you like to add a remark to?"
                messages.append({"role": "assistant", "content": msg})
                return {
                    **state,
                    "stage": "collecting_wo_number",
                    "intent": "add_wo_remark",
                    "wo_number": None,
                    "remark_text": remark_text,
                    "messages": messages,
                    "final_answer": msg,
                    "speak": msg,
                    "requires_more_info": True,
                }
            if len(remark_text) < api._MIN_LIFECYCLE_REASON_LEN:
                msg = "What remark should I add to this work order?"
                messages.append({"role": "assistant", "content": msg})
                return {
                    **state,
                    "stage": "collecting_remark_text",
                    "intent": "add_wo_remark",
                    "wo_number": wo_number,
                    "remark_text": remark_text,
                    "messages": messages,
                    "final_answer": msg,
                    "speak": msg,
                    "requires_more_info": True,
                }

            pre = api.get_workorder_full(
                user_id=state.get("user_id", ""),
                session=(state.get("context") or {}).get("wwts_session"),
                wo_number=wo_number,
                customer_codes=customer_codes,
            )
            if not pre.get("success"):
                msg = _friendly_err(pre.get("error")) or f"Work order {wo_number} could not be validated."
                messages.append({"role": "assistant", "content": msg})
                return {
                    **state,
                    "stage": "done",
                    "intent": "add_wo_remark",
                    "wo_number": wo_number,
                    "final_answer": msg,
                    "speak": msg,
                    "requires_more_info": False,
                }

            summary = _build_remark_summary(wo_number, pre.get("detail") or {}, remark_text)
            messages.append({"role": "assistant", "content": summary})
            return {
                **state,
                "stage": "confirming_remark",
                "intent": "add_wo_remark",
                "wo_number": wo_number,
                "remark_text": remark_text,
                "wo_detail": pre.get("detail") or {},
                "messages": messages,
                "final_answer": summary,
                "speak": summary,
                "requires_more_info": True,
            }
        # Focused read of a WO already in context ("find the remarks/parts/labor
        # on this work order") — read it, don't fall into the search loop.
        _wo_ctx = state.get("wo_number")
        _focus = _detect_get_focus(user_message or "") if user_message else None
        if (
            _wo_ctx
            and _focus
            and routed not in ("collecting_create", "collecting_close_reason", "collecting_reopen_reason", "collecting_remark_text")
            and not _detect_remark_intent(user_message or "")
            and state.get("intent") != "create_wo"
        ):
            msg = f"Fetching the {_focus} for work order {_wo_ctx}."
            messages.append({"role": "assistant", "content": msg})
            return {
                **state,
                "stage": "executing_get",
                "intent": "get_wo",
                "wo_number": _wo_ctx,
                "wo_get_focus": _focus,
                "messages": messages,
                "final_answer": msg,
                "speak": msg,
                "requires_more_info": False,
            }
        if routed == "collecting_search_criteria":
            if stage in ("collecting_create", "confirming_create") or state.get("intent") == "create_wo":
                routed = "collecting_create"
                new_intent = "create_wo"
            else:
                new_intent = "search_wo"
                if api._has_search_criteria(sf, multi_codes):
                    routed = "executing_list"
                else:
                    sf = _merge_search_filters(sf, _extract_search_filters_from_text(user_message or ""))
        elif routed == "collecting_create":
            new_intent = "create_wo"
        elif routed == "collecting_wo_number":
            new_intent = "get_wo"
            # A WO is already in context — answer about it, don't re-ask the number.
            if state.get("wo_number"):
                msg = f"Let me pull up work order {state['wo_number']}."
                messages.append({"role": "assistant", "content": msg})
                return {
                    **state,
                    "stage": "executing_get",
                    "intent": "get_wo",
                    "wo_number": state["wo_number"],
                    "messages": messages,
                    "final_answer": msg,
                    "speak": msg,
                    "requires_more_info": False,
                }
        elif routed == "collecting_close_reason":
            new_intent = "close_wo"
        elif routed == "collecting_reopen_reason":
            new_intent = "reopen_wo"
        elif routed == "collecting_remark_text":
            new_intent = "add_wo_remark"
        if routed:
            new_stage = routed
            msg = {
                "executing_list": "Let me check your open work orders.",
                "collecting_wo_number": "What work order number would you like to look up?",
                "collecting_wo_part_line": "Which part line number should I look up?",
                "collecting_search_criteria": (
                    "What should I search for — customer call number, site ID, model, serial, or WO number?"
                ),
                "collecting_create": "I can help create a work order. What is the product reference?",
                "executing_get_parts": "Let me get the parts for that work order.",
                "executing_get_labor": "Let me check labor on that work order.",
                "executing_get_labor_activities": "Let me check labor activities on that work order.",
                "executing_get_site": "Let me get the site information for that work order.",
                "executing_get_part_line": "Let me get that part line detail.",
            }.get(routed, "On it.")
            if routed == "executing_list" and new_intent == "search_wo":
                msg = _build_search_summary(sf)
            if routed == "collecting_create" and new_intent == "create_wo":
                missing = _missing_create_fields(
                    create_fields,
                    bool((context.get("customer_code") or "").strip()) or bool(customer_codes),
                    multi_codes,
                )
                if missing:
                    msg = "I still need " + ", ".join(missing) + "."
                else:
                    routed = "confirming_create"
                    new_stage = "confirming_create"
                    msg = _build_create_summary(create_fields)
            if (new_intent == "create_wo") and (new_stage == "collecting_create"):
                missing = _missing_create_fields(
                    create_fields,
                    bool((context.get("customer_code") or "").strip()) or bool(customer_codes),
                    multi_codes,
                )
                if missing:
                    msg = "I still need " + ", ".join(missing) + "."
                else:
                    new_stage = "confirming_create"
                    msg = _build_create_summary(create_fields)
        else:
            msgs_map = {
                "greeting": "I can list work orders, look up a WO, or create one. What would you like?",
                "intent": "Would you like to list work orders, get details on a specific one, or create a new one?",
                "collecting_wo_number": "What's the work order number you'd like to look up?",
                "collecting_wo_part_line": "Which part line number on this work order?",
                "collecting_search_criteria": (
                    "What should I search for — customer call number, site ID, model, serial, or WO number?"
                ),
                "collecting_create": "What's the product reference and contact name for the new work order?",
                "done": "Got it. Is there anything else I can help with?",
            }
            msg = msgs_map.get(stage, "How can I help with work orders?")
            new_stage = "intent" if stage in ("greeting", "done") else stage
            new_intent = state.get("intent")

        if (new_intent == "create_wo") and (new_stage == "collecting_create"):
            missing = _missing_create_fields(
                create_fields,
                bool((context.get("customer_code") or "").strip()) or bool(customer_codes),
                multi_codes,
            )
            if missing:
                msg = "I still need " + ", ".join(missing) + "."
            else:
                new_stage = "confirming_create"
                msg = _build_create_summary(create_fields)

    messages.append({"role": "assistant", "content": msg})
    result = {
        **state,
        "stage": new_stage,
        "messages": messages,
        "final_answer": msg,
        "speak": msg,
        "requires_more_info": new_stage not in _EXECUTING_STAGES
        and new_stage != "done",
    }
    if create_fields:
        result["create_fields"] = create_fields
    if new_intent:
        result["intent"] = new_intent
    if sf:
        result["search_filters"] = sf
    return result
