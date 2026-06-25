"""Canonical fact/correction helpers for the WWTS conversation state.

The legacy agent state is intentionally still supported. These helpers add a
small canonical layer that lets user corrections update shared facts first,
then mirror those values back into the existing flat fields.
"""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from wwts_agent import api


_CREATE_FACT_TO_FIELD = {
    "customer_code": "Customer Code",
    "product_ref": "Product Reference",
    "contact_name": "Contact Name",
    "contact_phone": "Contact Phone",
    "site_id": "Site ID",
}

_SEARCH_FACT_TO_FILTER = {
    "customer_code": "customer_code",
    "model": "model",
    "serial": "serial",
    "site_id": "site_id",
    "cust_call": "cust_call",
    "wo_number": "wo_number",
}

_PRODUCT_REF_STOPWORDS = {
    "a",
    "actually",
    "already",
    "and",
    "are",
    "be",
    "been",
    "correct",
    "correction",
    "did",
    "do",
    "does",
    "for",
    "got",
    "help",
    "instead",
    "is",
    "it",
    "make",
    "my",
    "no",
    "not",
    "of",
    "ok",
    "okay",
    "problem",
    "product",
    "reference",
    "resolve",
    "resolved",
    "should",
    "that",
    "the",
    "this",
    "to",
    "tried",
    "troubleshoot",
    "wrong",
    "yes",
}


def _is_plausible_product_ref(value: str | None) -> bool:
    candidate = (value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\-]{1,19}", candidate):
        return False
    return candidate.lower() not in _PRODUCT_REF_STOPWORDS


def hydrate_state(state: dict[str, Any]) -> dict[str, Any]:
    """Populate canonical facts/artifacts from the existing flat state."""
    out = dict(state)
    facts = deepcopy(out.get("facts") or {})

    def put(name: str, value: Any, *, source: str = "legacy") -> None:
        if value in (None, ""):
            return
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return
        facts.setdefault(name, {"value": value, "source": source, "confidence": 1.0})

    context = out.get("context") or {}
    create_fields = out.get("create_fields") or {}
    search_filters = out.get("search_filters") or {}

    put("customer_code", create_fields.get("Customer Code") or search_filters.get("customer_code") or context.get("customer_code"))
    put("product_ref", create_fields.get("Product Reference") or out.get("ts_product_ref"))
    put("product_desc", out.get("ts_product_desc"), source="api")
    put("contact_name", create_fields.get("Contact Name") or out.get("ts_name"))
    put("contact_phone", create_fields.get("Contact Phone"))
    put("site_id", create_fields.get("Site ID") or search_filters.get("site_id"))
    put("issue", out.get("ts_issue"))
    put("device", out.get("ts_device"))
    put("wo_number", out.get("wo_number") or search_filters.get("wo_number"))
    put("model", search_filters.get("model"))
    put("serial", search_filters.get("serial"))
    put("cust_call", search_filters.get("cust_call"))

    location = facts.get("location", {}).get("value") or {}
    if not location:
        location = {
            "city": create_fields.get("Customer City"),
            "state": create_fields.get("Customer State"),
            "postal_code": create_fields.get("Customer Postal Code"),
            "address": create_fields.get("Customer Address"),
        }
        location = {k: v for k, v in location.items() if v}
        if location:
            facts["location"] = {"value": location, "source": "legacy", "confidence": 1.0}

    out["facts"] = facts
    out.setdefault("active_task", _infer_active_task(out))
    out.setdefault("corrections", [])
    artifacts = dict(out.get("artifacts") or {})
    if out.get("wo_detail") or out.get("wo_parts") or out.get("wo_labor") or out.get("wo_site"):
        artifacts.setdefault("current_wo", {})
        artifacts["current_wo"].update(
            {
                "detail": out.get("wo_detail"),
                "remarks": out.get("wo_remarks"),
                "parts": out.get("wo_parts"),
                "labor": out.get("wo_labor"),
                "site": out.get("wo_site"),
            }
        )
    if out.get("wo_list"):
        artifacts.setdefault("search_results", out.get("wo_list"))
    out["artifacts"] = artifacts
    return out


def apply_user_corrections(
    state: dict[str, Any],
    user_message: str,
    *,
    customer_codes: list,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Apply obvious user corrections to canonical facts and dependent fields."""
    if not user_message:
        return state, []
    out = hydrate_state(state)
    updates = _extract_updates(user_message, customer_codes)
    if not updates:
        return out, []

    facts = deepcopy(out.get("facts") or {})
    corrections = list(out.get("corrections") or [])
    applied: list[dict[str, Any]] = []
    now = datetime.now(UTC).isoformat()
    for field, value in updates.items():
        old = (facts.get(field) or {}).get("value")
        if value in (None, "") or str(value).strip() == str(old or "").strip():
            continue
        facts[field] = {"value": value, "source": "correction", "confidence": 1.0}
        entry = {
            "ts": now,
            "field": field,
            "old": old,
            "new": value,
            "scope": _correction_scope(out),
            "reason": "user_correction",
        }
        corrections.append(entry)
        applied.append(entry)

    if not applied:
        return out, []
    out["facts"] = facts
    out["corrections"] = corrections
    out = sync_legacy_fields(out, changed_fields={c["field"] for c in applied})
    return out, applied


def sync_legacy_fields(
    state: dict[str, Any],
    *,
    changed_fields: set[str] | None = None,
) -> dict[str, Any]:
    """Mirror canonical facts into legacy fields used by the current FSM."""
    out = dict(state)
    facts = out.get("facts") or {}
    changed_fields = changed_fields or set()

    create_fields = dict(out.get("create_fields") or {})
    for fact, field in _CREATE_FACT_TO_FIELD.items():
        value = _fact_value(facts, fact)
        if value:
            create_fields[field] = value
    location = _fact_value(facts, "location") or {}
    if isinstance(location, dict):
        if location.get("city"):
            create_fields["Customer City"] = location["city"]
        if location.get("state"):
            create_fields["Customer State"] = location["state"]
        if location.get("postal_code"):
            create_fields["Customer Postal Code"] = location["postal_code"]
        if location.get("address"):
            create_fields["Customer Address"] = location["address"]
    if create_fields:
        api._split_city_state_zip(create_fields)
        out["create_fields"] = create_fields

    search_filters = api._normalize_search_filters(dict(out.get("search_filters") or {}))
    for fact, key in _SEARCH_FACT_TO_FILTER.items():
        value = _fact_value(facts, fact)
        if value:
            search_filters[key] = value
    if search_filters:
        out["search_filters"] = search_filters

    if _fact_value(facts, "wo_number"):
        new_wo = str(_fact_value(facts, "wo_number")).upper()
        old_wo = out.get("wo_number")
        out["wo_number"] = new_wo
        active_task = dict(out.get("active_task") or {})
        if active_task.get("kind") in {"get", "close", "reopen", "remark"} or old_wo:
            active_task["target_wo"] = new_wo
            out["active_task"] = active_task
        if "wo_number" in changed_fields and old_wo and str(old_wo).upper() != new_wo:
            out.update(
                {
                    "wo_detail": None,
                    "wo_remarks": None,
                    "wo_parts": None,
                    "wo_labor": None,
                    "wo_site": None,
                    "wo_part_line_detail": None,
                    "wo_labor_activities": None,
                }
            )
            artifacts = dict(out.get("artifacts") or {})
            artifacts.pop("current_wo", None)
            out["artifacts"] = artifacts

    if _fact_value(facts, "product_ref"):
        out["ts_product_ref"] = _fact_value(facts, "product_ref")
    if _fact_value(facts, "product_desc"):
        out["ts_product_desc"] = _fact_value(facts, "product_desc")
    if _fact_value(facts, "issue"):
        out["ts_issue"] = _fact_value(facts, "issue")
    if _fact_value(facts, "device"):
        out["ts_device"] = _fact_value(facts, "device")
    if _fact_value(facts, "contact_name"):
        out["ts_name"] = _fact_value(facts, "contact_name")
    return out


def _extract_updates(text: str, customer_codes: list) -> dict[str, Any]:
    lower = text.lower()
    if not any(k in lower for k in ("not ", "actually", "correction", "correct", "change", "make that", "instead")):
        return {}

    updates: dict[str, Any] = {}
    product = _first_match(
        text,
        [
            r"\bproduct(?:\s+reference)?\s+(?:is|should be|to|=|:)\s*([A-Za-z0-9\-]+)",
            r"\b(?:make that|actually|correct(?:ion)?|change(?: it)? to)\s+([A-Za-z0-9\-]{2,20})\b",
            r"\b([A-Za-z0-9\-]{2,20})\s+not\s+[A-Za-z0-9\-]{2,20}\b",
        ],
    )
    if product and not product.upper().startswith(("WU", "WO")):
        if _is_plausible_product_ref(product):
            updates["product_ref"] = product.upper()

    wo = _first_match(
        text,
        [
            r"\b(?:wo|work\s+order)\s*(?:is|should be|to|#|=|:)?\s*([A-Za-z]*\d+[A-Za-z0-9]*)",
            r"\bnot\s+(?:wo\s*)?[A-Za-z]*\d+[A-Za-z0-9]*[,\s]+(?:it\s+(?:is|'?s)\s+)?([A-Za-z]*\d+[A-Za-z0-9]*)",
        ],
    )
    if wo:
        updates["wo_number"] = wo.upper()

    model = _first_match(text, [r"\bmodel\s+(?:is|should be|to|=|:)?\s*([A-Za-z0-9\-]+)"])
    if model:
        updates["model"] = model.lower()
    serial = _first_match(text, [r"\bserial(?:\s+number)?\s+(?:is|should be|to|=|:)?\s*([A-Za-z0-9\-]+)"])
    if serial:
        updates["serial"] = serial.lower()
    site = _first_match(text, [r"\bsite\s*(?:id)?\s+(?:is|should be|to|=|:)?\s*([A-Za-z0-9\-]+)"])
    if site:
        updates["site_id"] = site.upper()
    cust_call = _first_match(text, [r"\bcustomer\s+call(?:\s+number)?\s+(?:is|should be|to|=|:)?\s*([A-Za-z0-9\-]+)"])
    if cust_call:
        updates["cust_call"] = cust_call.lower()

    code = _match_customer(text, customer_codes)
    if code:
        updates["customer_code"] = code

    issue = _first_match(text, [r"\b(?:issue|problem)\s+(?:is|should be|was|to|=|:)\s*(.+)$", r"\bactually\s+(.+)$"])
    if issue and any(k in lower for k in ("issue", "problem", "overheat", "power", "broken", "error")):
        updates["issue"] = issue.strip().rstrip(".")

    return updates


def _infer_active_task(state: dict[str, Any]) -> dict[str, Any]:
    intent = state.get("intent")
    kind = {
        "create_wo": "create",
        "search_wo": "search",
        "list_wo": "list",
        "get_wo": "get",
        "get_wo_parts": "get",
        "get_wo_labor": "get",
        "get_wo_labor_activities": "get",
        "get_site": "get",
        "close_wo": "close",
        "reopen_wo": "reopen",
        "add_wo_remark": "remark",
        "troubleshoot": "troubleshoot",
    }.get(intent or "", intent or "")
    task = {"kind": kind} if kind else {}
    if state.get("wo_number"):
        task["target_wo"] = state.get("wo_number")
    return task


def _correction_scope(state: dict[str, Any]) -> str:
    task = state.get("active_task") or _infer_active_task(state)
    if task.get("target_wo"):
        return f"wo:{task['target_wo']}"
    if task.get("kind"):
        return "active_task"
    return "global"


def _fact_value(facts: dict[str, Any], name: str) -> Any:
    item = facts.get(name)
    if isinstance(item, dict):
        return item.get("value")
    return item


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _match_customer(text: str, customer_codes: list) -> str | None:
    compact = re.sub(r"[^a-z0-9]", "", text.lower())
    for c in customer_codes or []:
        code = (c.get("code") if isinstance(c, dict) else str(c)).strip()
        name = (c.get("name", "") if isinstance(c, dict) else "").strip()
        variants = {code, name}
        for value in variants:
            norm = re.sub(r"[^a-z0-9]", "", value.lower())
            if norm and norm in compact:
                return code
    return None
