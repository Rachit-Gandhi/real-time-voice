"""Thin wrappers around portals.wwits API calls that return plain dicts."""
import datetime
import hashlib
import json
import logging
import os
import re
from dataclasses import asdict

import requests

from portals.wwits.apis.rest_services import (
    GTCallInterface,
    GTService,
    GTServiceAction,
    GTServiceSetUp,
)
from portals.wwits.environment import Environment, wwits_env

_DEFAULT_ENV = "QA"
_DEFAULT_SRC = "WMP"
_AUDIT_LOGGER = logging.getLogger("wwts_agent.audit")


def ensure_env() -> None:
    if wwits_env.is_init:
        return
    try:
        Environment(environment=_DEFAULT_ENV, source=_DEFAULT_SRC,
                    config_file=wwits_env.config, path="")
    except Exception:
        pass


_SESSION_EXPIRED_MARKERS = (
    "expecting value: line 1 column 1",  # WWTS returned empty/non-JSON body
    "the request is invalid",            # WWTS 400 for a dead session
    "session expired",
    "session has expired",
    "invalid session",
    "not logged in",
)


def is_session_expired_error(msg: object) -> bool:
    """True when a WWTS error signals the portal session is dead and re-login is needed."""
    low = str(msg or "").lower()
    return any(m in low for m in _SESSION_EXPIRED_MARKERS)


def _to_dict(obj) -> dict:
    if isinstance(obj, dict):
        return dict(obj)
    try:
        return asdict(obj)
    except Exception:
        return vars(obj) if hasattr(obj, "__dict__") else {}


def _normalize_customer_codes(customer_codes: "str | list") -> list[str]:
    """Normalise login customer_codes to a list of code strings."""
    if isinstance(customer_codes, str):
        return [customer_codes.strip()] if customer_codes.strip() else []
    return [
        (c["code"] if isinstance(c, dict) else str(c)).strip()
        for c in customer_codes
        if c and str(c["code"] if isinstance(c, dict) else c).strip()
    ]


def _assert_wo_in_scope(detail: dict, customer_codes: "str | list") -> None:
    """Raise ValueError when WO custcode is outside the user's customer scope."""
    if not detail:
        raise ValueError("Work order detail is missing.")
    custcode = (detail.get("custcode") or "").strip()
    if not custcode:
        raise ValueError("Work order has no customer code.")
    allowed = _normalize_customer_codes(customer_codes)
    if not allowed:
        raise ValueError("No customer codes available for scope check.")
    allowed_upper = {code.upper() for code in allowed}
    if custcode.upper() not in allowed_upper:
        raise ValueError(
            f"Work order customer {custcode} is not in your authorized customer list."
        )


def log_wwts_action(
    action: str,
    *,
    user_id: str = "",
    thread_id: str = "",
    **details: object,
) -> None:
    """Audit hook for guarded lifecycle writes (create/close/reopen in later phases)."""
    parts = [f"action={action}", f"user_id={user_id}", f"thread_id={thread_id}"]
    for key, val in sorted(details.items()):
        parts.append(f"{key}={val}")
    _AUDIT_LOGGER.info("wwts_audit %s", " ".join(parts))


_DEFAULT_CREATE_AUTH_NAMES = (
    "RequestForOpen",
    "REQUESTFOROPEN",
    "request_for_open",
    "WoRequestOpen",
    "GTRequestForOpen",
    "BatchCallOpen",
    "DashBatchCallOpen",
    "menuBatchOpen",
)


def _create_auth_name_set() -> set[str]:
    raw = os.getenv("WWTS_CREATE_FUNCTION_NAMES", "")
    names = list(_DEFAULT_CREATE_AUTH_NAMES)
    if raw.strip():
        names.extend(part.strip() for part in raw.split(",") if part.strip())
    return {n.upper() for n in names}


def is_authorized_for_create(authorized_functions: list[str]) -> bool:
    """True when FunctionAuthorizeList includes a known create/open permission."""
    if not authorized_functions:
        return False
    allowed = _create_auth_name_set()
    user_names = {str(f).strip().upper() for f in authorized_functions if str(f).strip()}
    if user_names & allowed:
        return True
    return any("REQUEST" in name and "OPEN" in name for name in user_names)


_DEFAULT_CLOSE_AUTH_NAMES = (
    "CloseCall",
    "CLOSECALL",
    "wo_close",
    "WOClose",
    "GTServiceAction.CloseCall",
)
_DEFAULT_REOPEN_AUTH_NAMES = (
    "ReopenWO",
    "REOPENWO",
    "wo_reopen",
    "WOReOpen",
    "GTServiceAction.ReopenWO",
)
_DEFAULT_REMARK_AUTH_NAMES = (
    "InsertCallRemark",
    "INSERTCALLREMARK",
    "remark_new",
    "RemarkNew",
    "GTServiceAction.InsertCallRemark",
)

_MIN_LIFECYCLE_REASON_LEN = 5


def _auth_name_set(defaults: tuple[str, ...], env_var: str) -> set[str]:
    raw = os.getenv(env_var, "")
    names = list(defaults)
    if raw.strip():
        names.extend(part.strip() for part in raw.split(",") if part.strip())
    return {n.upper() for n in names}


def is_authorized_for_close(authorized_functions: list[str]) -> bool:
    if not authorized_functions:
        return False
    allowed = _auth_name_set(_DEFAULT_CLOSE_AUTH_NAMES, "WWTS_CLOSE_FUNCTION_NAMES")
    user_names = {str(f).strip().upper() for f in authorized_functions if str(f).strip()}
    if user_names & allowed:
        return True
    return any("CLOSE" in name and "CALL" in name for name in user_names)


def is_authorized_for_reopen(authorized_functions: list[str]) -> bool:
    if not authorized_functions:
        return False
    allowed = _auth_name_set(_DEFAULT_REOPEN_AUTH_NAMES, "WWTS_REOPEN_FUNCTION_NAMES")
    user_names = {str(f).strip().upper() for f in authorized_functions if str(f).strip()}
    if user_names & allowed:
        return True
    return any("REOPEN" in name for name in user_names)


def is_authorized_for_remark(authorized_functions: list[str]) -> bool:
    if not authorized_functions:
        return False
    allowed = _auth_name_set(_DEFAULT_REMARK_AUTH_NAMES, "WWTS_REMARK_FUNCTION_NAMES")
    user_names = {str(f).strip().upper() for f in authorized_functions if str(f).strip()}
    if user_names & allowed:
        return True
    return any("REMARK" in name for name in user_names)


def is_wo_closed(detail: dict) -> bool:
    """True when detail indicates the WO is already closed."""
    if not detail:
        return False
    status = (detail.get("vstatus") or "").strip().lower()
    if any(k in status for k in ("clos", "complet", "resolv", "cancel")):
        return True
    closed_dt = (detail.get("closed") or "").strip()
    if closed_dt and closed_dt.lower() not in ("", "null", "none", "0"):
        return True
    last_stop = (detail.get("laststop") or "").strip().lower()
    if last_stop in ("closed", "complete", "completed", "resolved"):
        return True
    return False


def is_wo_open(detail: dict) -> bool:
    return not is_wo_closed(detail)


def _normalize_close_fields(fields: dict) -> dict:
    out: dict = {}
    for key, val in dict(fields or {}).items():
        if isinstance(val, str):
            val = val.strip()
        if val not in (None, ""):
            out[key] = val
    reason = out.get("Close Reason") or out.get("close_reason") or ""
    if reason and "Close Reason" not in out:
        out["Close Reason"] = reason
    return out


def missing_close_fields(fields: dict) -> list[str]:
    reason = (_normalize_close_fields(fields).get("Close Reason") or "").strip()
    if len(reason) < _MIN_LIFECYCLE_REASON_LEN:
        return ["Close Reason (at least 5 characters)"]
    return []


def close_fields_fingerprint(wo_number: str, fields: dict) -> str:
    payload = json.dumps(
        {"wo": (wo_number or "").strip().upper(), "fields": _normalize_close_fields(fields)},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def reopen_reason_fingerprint(wo_number: str, reason: str) -> str:
    payload = json.dumps(
        {"wo": (wo_number or "").strip().upper(), "reason": (reason or "").strip()},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def remark_fingerprint(wo_number: str, remark_text: str, rem_type: str) -> str:
    payload = json.dumps(
        {
            "wo": (wo_number or "").strip().upper(),
            "remark_text": (remark_text or "").strip(),
            "rem_type": (rem_type or "").strip().upper(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _detail_field(detail: dict, *keys: str, default: object = ""):
    for key in keys:
        val = detail.get(key)
        if val is not None and str(val).strip() != "":
            return val
    return default


def _close_code(fields: dict, *keys: str, env: str) -> str:
    """A WWTS close code from explicit close_fields, else an env default.

    WWTS validates Problem/Cause/Repair as CODES (not free text), so the
    free-text reason must NOT be used here — it goes in FixDesc instead.
    """
    for k in keys:
        v = fields.get(k)
        if v not in (None, ""):
            return str(v).strip()
    return (os.getenv(env, "") or "").strip()


def missing_close_codes(close_fields: dict) -> list[str]:
    """Problem/Cause/Repair codes still needed before CloseCall will be accepted."""
    fields = _normalize_close_fields(close_fields)
    missing = []
    if not _close_code(fields, "Problem Code", "ProblemCode", "Problem", env="WWTS_CLOSE_PROBLEM_CODE"):
        missing.append("Problem Code")
    if not _close_code(fields, "Cause Code", "CauseCode", "Cause", env="WWTS_CLOSE_CAUSE_CODE"):
        missing.append("Cause Code")
    if not _close_code(fields, "Repair Code", "RepairCode", "Repair", env="WWTS_CLOSE_REPAIR_CODE"):
        missing.append("Repair Code")
    return missing


def _build_close_call_kwargs(detail: dict, close_fields: dict) -> dict:
    fields = _normalize_close_fields(close_fields)
    reason = (fields.get("Close Reason") or "").strip()
    if len(reason) < _MIN_LIFECYCLE_REASON_LEN:
        raise ValueError(
            f"Close reason must be at least {_MIN_LIFECYCLE_REASON_LEN} characters."
        )

    # Problem/Cause/Repair are CODES validated by WWTS. Putting the free-text
    # reason here caused "Problem Code field is not valid". The reason is the
    # FixDesc; codes come from close_fields or WWTS_CLOSE_*_CODE env defaults.
    missing_codes = missing_close_codes(fields)
    if missing_codes:
        raise ValueError(
            "Closing this work order needs valid WWTS close codes: "
            + ", ".join(missing_codes)
            + ". Provide them, or set WWTS_CLOSE_PROBLEM_CODE / "
            "WWTS_CLOSE_CAUSE_CODE / WWTS_CLOSE_REPAIR_CODE."
        )

    now = datetime.datetime.now().strftime("%m/%d/%y %H:%M")
    entity = str(
        _detail_field(detail, "entity", "Entity", "custcode", "CustCode", default="WO")
    )
    entity_recid = int(_detail_field(detail, "entityrecid", "EntityRecid", "EntityRecID", default=0) or 0)
    entity_count = int(_detail_field(detail, "entitycount", "EntityCount", default=1) or 1)

    fix_desc = (fields.get("FixDesc") or _detail_field(detail, "fixdescription", "FixDescription") or reason)
    problem = _close_code(fields, "Problem Code", "ProblemCode", "Problem", env="WWTS_CLOSE_PROBLEM_CODE")
    cause = _close_code(fields, "Cause Code", "CauseCode", "Cause", env="WWTS_CLOSE_CAUSE_CODE")
    repair = _close_code(fields, "Repair Code", "RepairCode", "Repair", env="WWTS_CLOSE_REPAIR_CODE")

    return {
        "Entity": entity,
        "EntityRecID": entity_recid,
        "EntityCount": entity_count,
        "EquipSerial": str(_detail_field(detail, "equip_serial", "EquipSerial", default="")),
        "FixDesc": str(fix_desc)[:500],
        "CloseDateTime": now,
        "CSR": str(_detail_field(detail, "CSR", "csr", default="")),
        "Problem": str(problem)[:200],
        "Cause": str(cause)[:200],
        "Repair": str(repair)[:200],
    }


def preflight_close_workorder(
    user_id: str,
    session: int,
    wo_number: str,
    customer_codes: "str | list",
) -> dict:
    """Load WO, enforce scope, and detect already-closed."""
    pre = _wo_preflight_scope(user_id, session, wo_number, customer_codes)
    if not pre["success"]:
        return {**pre, "already_closed": False}
    detail = pre["detail"]
    if is_wo_closed(detail):
        return {
            "success": False,
            "detail": detail,
            "error": (
                f"Work order {wo_number} is already closed. "
                "You can reopen it or ask for status instead."
            ),
            "already_closed": True,
        }
    return {"success": True, "detail": detail, "error": "", "already_closed": False}


def preflight_reopen_workorder(
    user_id: str,
    session: int,
    wo_number: str,
    customer_codes: "str | list",
) -> dict:
    pre = _wo_preflight_scope(user_id, session, wo_number, customer_codes)
    if not pre["success"]:
        return {**pre, "already_open": False}
    detail = pre["detail"]
    if is_wo_open(detail):
        return {
            "success": False,
            "detail": detail,
            "error": (
                f"Work order {wo_number} is already open. "
                "You can close it or ask for status instead."
            ),
            "already_open": True,
        }
    return {"success": True, "detail": detail, "error": "", "already_open": False}


def close_workorder(
    user_id: str,
    session: int,
    wo_number: str,
    close_fields: dict,
    customer_codes: "str | list",
    *,
    detail: dict | None = None,
) -> dict:
    ensure_env()
    fields = _normalize_close_fields(close_fields)
    missing = missing_close_fields(fields)
    if missing:
        return {
            "success": False,
            "RC": -1,
            "ResultMsg": "Missing: " + ", ".join(missing),
            "error": "Missing: " + ", ".join(missing),
        }

    if detail is None:
        pre = preflight_close_workorder(user_id, session, wo_number, customer_codes)
        if not pre["success"]:
            return {
                "success": False,
                "RC": -1,
                "ResultMsg": pre.get("error", ""),
                "error": pre.get("error", ""),
                "already_closed": pre.get("already_closed", False),
            }
        detail = pre["detail"]
    else:
        try:
            _assert_wo_in_scope(detail, customer_codes)
        except ValueError as exc:
            return {"success": False, "RC": -1, "ResultMsg": str(exc), "error": str(exc)}
        if is_wo_closed(detail):
            return {
                "success": False,
                "RC": -1,
                "ResultMsg": "Work order is already closed.",
                "error": "Work order is already closed.",
                "already_closed": True,
            }

    order_no = _order_no_from_detail(detail, wo_number)
    try:
        kwargs = _build_close_call_kwargs(detail, fields)
        resp = GTServiceAction().CloseCall(user_id, session, order_no, **kwargs)
        rc = int(getattr(resp, "RC", -1))
        msg = getattr(resp, "ResultMsg", "") or ""
        return {
            "success": rc == 0,
            "RC": rc,
            "ResultMsg": msg,
            "error": "" if rc == 0 else msg or f"Close failed with RC={rc}",
            "OrderNum": order_no,
        }
    except Exception as exc:
        return {"success": False, "RC": -1, "ResultMsg": str(exc), "error": str(exc)}


def reopen_workorder(
    user_id: str,
    session: int,
    wo_number: str,
    reopen_reason: str,
    customer_codes: "str | list",
    *,
    detail: dict | None = None,
) -> dict:
    ensure_env()
    reason = (reopen_reason or "").strip()
    if len(reason) < _MIN_LIFECYCLE_REASON_LEN:
        return {
            "success": False,
            "RC": -1,
            "ResultMsg": f"Reopen reason must be at least {_MIN_LIFECYCLE_REASON_LEN} characters.",
            "error": f"Reopen reason must be at least {_MIN_LIFECYCLE_REASON_LEN} characters.",
        }

    if detail is None:
        pre = preflight_reopen_workorder(user_id, session, wo_number, customer_codes)
        if not pre["success"]:
            return {
                "success": False,
                "RC": -1,
                "ResultMsg": pre.get("error", ""),
                "error": pre.get("error", ""),
                "already_open": pre.get("already_open", False),
            }
        detail = pre["detail"]
    else:
        try:
            _assert_wo_in_scope(detail, customer_codes)
        except ValueError as exc:
            return {"success": False, "RC": -1, "ResultMsg": str(exc), "error": str(exc)}
        if is_wo_open(detail):
            return {
                "success": False,
                "RC": -1,
                "ResultMsg": "Work order is already open.",
                "error": "Work order is already open.",
                "already_open": True,
            }

    order_no = _order_no_from_detail(detail, wo_number)
    try:
        resp = GTServiceAction().ReopenWO(
            user_id, session, order_no, ReOpenReason=reason
        )
        rc = int(getattr(resp, "RC", -1))
        msg = getattr(resp, "ResultMsg", "") or ""
        return {
            "success": rc == 0,
            "RC": rc,
            "ResultMsg": msg,
            "error": "" if rc == 0 else msg or f"Reopen failed with RC={rc}",
            "OrderNum": order_no,
        }
    except Exception as exc:
        return {"success": False, "RC": -1, "ResultMsg": str(exc), "error": str(exc)}


def _remark_default_type() -> str:
    return (os.getenv("WWTS_REMARK_DEFAULT_REMTYPE", "GEN") or "GEN").strip()


def _wo_alt_num_from_detail(detail: dict | None) -> str:
    """The WO's alternate/customer-call reference (WOAltNum) from a detail dict."""
    if not isinstance(detail, dict):
        return ""
    for key in ("woaltnum", "WOAltNum", "altref", "AltRef", "custcall", "CustCall", "vendcallnbr"):
        val = detail.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def _root_cedic_from_detail(detail: dict | None) -> str:
    """RootCedic for a WO. Prefer an explicit value; else derive ASDS-<custcode>
    (the same convention create uses)."""
    if not isinstance(detail, dict):
        return ""
    for key in ("rootcedic", "RootCedic", "RootCEDIC"):
        val = detail.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    custcode = (detail.get("custcode") or detail.get("CustCode") or "").strip()
    return f"ASDS-{custcode}" if custcode else ""


def _remark_new_params(order_no: str, note: str, rem_type: str, detail: dict | None) -> dict:
    """Build RemarkNew Parms with the field names the WWTS endpoint expects.

    remove_empty() on the portal side drops blank values, so optional fields
    (WOAltNum, WOMajAct) are simply omitted when unknown.
    """
    params: dict = {
        "WONumber": order_no,
        "WOAltNum": _wo_alt_num_from_detail(detail),
        "RootCedic": _root_cedic_from_detail(detail),
        "WORem": note,
        "WOPage": False,
    }
    # Only send a major-activity code when it's a real one (the "GEN" default is
    # not a valid WOMajAct; let the server apply its own default).
    maj = (rem_type or "").strip()
    if maj and maj.upper() != "GEN":
        params["WOMajAct"] = maj
    return {k: v for k, v in params.items() if v not in ("", None)}


def _sanitize_remark(text: str) -> str:
    """WWTS truncates/garbles remark text on certain characters (apostrophes/
    quotes), so normalise to a plain ASCII-ish single line before sending."""
    t = (text or "")
    t = t.replace("’", "'").replace("‘", "'")
    t = t.replace("“", '"').replace("”", '"')
    t = t.replace("'", "").replace('"', "").replace("`", "")
    t = re.sub(r"[\r\n\t]+", " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


def add_workorder_remark(
    user_id: str,
    session: int,
    wo_number: str,
    remark_text: str,
    customer_codes: "str | list",
    *,
    detail: dict | None = None,
    rem_type: str | None = None,
) -> dict:
    ensure_env()
    note = _sanitize_remark(remark_text)
    if len(note) < _MIN_LIFECYCLE_REASON_LEN:
        return {
            "success": False,
            "RC": -1,
            "ResultMsg": f"Remark text must be at least {_MIN_LIFECYCLE_REASON_LEN} characters.",
            "error": f"Remark text must be at least {_MIN_LIFECYCLE_REASON_LEN} characters.",
        }

    if detail is None:
        pre = _wo_preflight_scope(user_id, session, wo_number, customer_codes)
        if not pre["success"]:
            return {
                "success": False,
                "RC": -1,
                "ResultMsg": pre.get("error", ""),
                "error": pre.get("error", ""),
            }
        detail = pre["detail"]
    else:
        try:
            _assert_wo_in_scope(detail, customer_codes)
        except ValueError as exc:
            return {"success": False, "RC": -1, "ResultMsg": str(exc), "error": str(exc)}

    order_no = _order_no_from_detail(detail, wo_number)
    remark_type = (rem_type or _remark_default_type()).strip()

    # WWTS "RemarkNew" expects specific Parm names: the remark text goes in
    # WORem (NOT RemData), and WOAltNum is the WO's alternate/customer-call ref.
    # Sending the wrong names left WORem empty and triggered server-side
    # "woaltnum field is not valid" errors. (GTServiceAction has no
    # InsertCallRemark, so remark_new is the only path.)
    params = _remark_new_params(order_no, note, remark_type, detail)
    try:
        resp = GTCallInterface().remark_new(user_id, session, **params)
    except Exception as exc:
        return {"success": False, "RC": -1, "ResultMsg": str(exc), "error": str(exc)}

    rc = int(getattr(resp, "RC", -1))
    msg = getattr(resp, "ResultMsg", "") or ""
    return {
        "success": rc == 0,
        "RC": rc,
        "ResultMsg": msg,
        "error": "" if rc == 0 else msg or f"Remark write failed with RC={rc}",
        "OrderNum": order_no,
        "RemType": remark_type,
    }


def _product_ref_modes() -> list[str]:
    """Candidate ``mode`` segments for the ProductReference REST call.

    The portal expects a mode in the URL (.../ProductRef/{cust}/{mode}); its
    valid value isn't documented in this repo. If WWTS_PRODUCT_REF_MODE is set
    we use only that; otherwise we try a few common values and stop at the first
    that returns products. Enrichment only — failure is non-fatal.
    """
    override = (os.getenv("WWTS_PRODUCT_REF_MODE") or "").strip()
    if override:
        return [override]
    return ["C", "U", ""]


def _parse_product_ref_response(resp) -> list[dict]:
    if not (getattr(resp, "success", False) or getattr(resp, "RC", -1) in (0, 2)):
        return []
    products: list[dict] = []
    for r in (resp.results() or []):
        raw = _to_dict(r)
        products.append(
            {
                "code": str(raw.get("CustomerPartMaster", "") or "").strip(),
                "description": str(raw.get("description", "") or "").strip(),
                "type": str(raw.get("Type", "") or "").strip(),
                "service_type": str(raw.get("servicetype", "") or "").strip(),
                "wo_type": str(raw.get("WOType", "") or "").strip(),
                "subdivision": str(raw.get("subdivision", "") or "").strip(),
            }
        )
    return products


def lookup_product_reference(
    user_id: str,
    session: int,
    cust_code: str,
    product_ref: str,
    mode: str | None = None,
) -> dict:
    """Resolve a product reference (CustomerPartMaster, e.g. "BDQ") to its
    catalog details for a customer.

    Returns {success, product, products, error}. ``product`` is the matching
    entry (or None if the code isn't found), with keys: code, description,
    type, service_type, wo_type, subdivision. This is an enrichment call — the
    caller should degrade gracefully when success is False or product is None.
    """
    ensure_env()
    code = (cust_code or "").strip()
    target = (product_ref or "").strip().upper()
    if not code:
        return {"success": False, "product": None, "products": [], "error": "Customer code required."}

    modes = [mode] if mode else _product_ref_modes()
    products: list[dict] = []
    last_err = ""
    for m in modes:
        try:
            resp = GTServiceSetUp().GetProductReference(user_id, session, code, m)
        except Exception as exc:  # network/parse/session errors — try next mode
            last_err = str(exc)
            continue
        products = _parse_product_ref_response(resp)
        if products:
            break
        last_err = last_err or (getattr(resp, "ResultMsg", "") or "")

    if not products:
        return {"success": False, "product": None, "products": [], "error": last_err}

    match = next((p for p in products if p["code"].upper() == target), None)
    return {"success": True, "product": match, "products": products, "error": ""}


def assert_create_customer_in_scope(customer_code: str, customer_codes: "str | list") -> None:
    """Ensure create customer code is within login customer_codes."""
    code = (customer_code or "").strip()
    if not code:
        raise ValueError("Customer Code is required to create a work order.")
    _assert_wo_in_scope({"custcode": code}, customer_codes)


def _safe_wo_results(resp, normalizer=None) -> list[dict]:
    if resp.success or getattr(resp, "RC", -1) == 2:
        results = resp.results()
        if not results:
            return []
        if normalizer:
            return [normalizer(r) for r in results]
        return [_to_dict(r) for r in results]
    return []


_WO_PART_FIELD_ALIASES = {
    "LineNum": "linenum",
    "PartNum": "partnum",
    "QtyOrd": "qtyord",
    "LineStatus": "linestatus",
    "Descr": "descr",
    "Location": "location",
    "QtyUsed": "qtyused",
    "PartRetCd": "partretcd",
    "NonRetCd": "nonretcd",
    "ReturnQty": "returnqty",
    "ReturnWaybill": "retwaybill",
    "RetCarrier": "retcarrier",
    "Returned": "returned",
    "ShipCarrier": "shipcarrier",
    "ShipWaybill": "shipwaybill",
    "Shipped": "shipped",
    "Consume": "consume",
    "SerialInstalled": "serialinstalled",
    "SerialDeinstalled": "serialdeinstalled",
    "PartNumDeinstalled": "partnumdeinstalled",
    "FromWhse": "fromwhse",
    "ToWhse": "towhse",
}


def _normalize_wo_part(part) -> dict:
    raw = _to_dict(part)
    return {_WO_PART_FIELD_ALIASES.get(key, key): value for key, value in raw.items()}


def _raw_call_parts(gts: GTService, user_id: str, session: int, order_no: str) -> list[dict]:
    url = gts.get_url(user_id, session, suffix=f"{order_no}/Parts")
    response = requests.get(url, headers=gts.headers, params={})
    payload = response.json() or {}
    parms = payload.get("Parms") or {}
    rc = str(parms.get("RC", "0")).strip()
    if rc not in ("0", "2"):
        return []
    rows = payload.get("WO") or []
    if isinstance(rows, dict):
        rows = [rows]
    return [_normalize_wo_part(row) for row in rows if row]


def _get_call_parts(gts: GTService, user_id: str, session: int, order_no: str) -> list[dict]:
    try:
        return _safe_wo_results(
            gts.GetCallParts(user_id, session, order_no),
            normalizer=_normalize_wo_part,
        )
    except Exception as exc:
        if "WOPartsSchema" not in str(exc):
            raise
        return _raw_call_parts(gts, user_id, session, order_no)


_SEARCH_FILTER_PORTAL_KEYS = {
    "cust_call": "CustCall",
    "site_id": "SiteID",
    "model": "Model",
    "serial": "Serial",
    "wo_number": "WO",
    "alt_ref": "AltRef",
    "vendor_call": "VendCallNbr",
    "call_type": "CallType",
}


def _query_orders_for_code(
    user_id: str,
    session: int,
    code: str,
    since: str,
    status: str,
    portal_filters: dict | None = None,
) -> list[dict]:
    try:
        extra = dict(portal_filters or {})
        resp = GTService().QueryCustomerOrders(
            user_id, session, custcode=code, opensince=since, wostatus=status, **extra
        )
        # RC=2 means "no records found" in the WWTS API — not a system error
        if resp.success or getattr(resp, "RC", -1) == 2:
            results = resp.results()
            return [_to_dict(o) for o in results] if results else []
    except Exception:
        pass
    return []


def _normalize_search_filters(filters: dict) -> dict:
    """Normalize search_filters dict keys and string values."""
    raw = dict(filters or {})
    out: dict = {}
    key_aliases = {
        "customer code": "customer_code",
        "customer_code": "customer_code",
        "customer call": "cust_call",
        "customer call number": "cust_call",
        "custcall": "cust_call",
        "cust_call": "cust_call",
        "site id": "site_id",
        "site_id": "site_id",
        "model": "model",
        "serial": "serial",
        "serial number": "serial",
        "wo number": "wo_number",
        "wo_number": "wo_number",
        "wo status": "wo_status",
        "wo_status": "wo_status",
        "days back": "days_back",
        "days_back": "days_back",
        "last": "result_limit",
        "limit": "result_limit",
        "result_limit": "result_limit",
        "alt ref": "alt_ref",
        "alt_ref": "alt_ref",
    }
    for key, val in raw.items():
        if val is None:
            continue
        norm_key = key_aliases.get(str(key).strip().lower(), str(key).strip().lower())
        if norm_key in ("days_back", "result_limit"):
            try:
                out[norm_key] = int(val)
            except (TypeError, ValueError):
                pass
            continue
        if isinstance(val, str):
            val = val.strip()
        if val != "":
            out[norm_key] = val
    if out.get("wo_status"):
        out["wo_status"] = str(out["wo_status"]).upper()[:1]
    return out


def _search_portal_filters(filters: dict) -> dict:
    """Map normalized search_filters to QueryCustomerOrders Parms keys."""
    portal: dict = {}
    for key, portal_key in _SEARCH_FILTER_PORTAL_KEYS.items():
        val = filters.get(key)
        if val is not None and str(val).strip():
            portal[portal_key] = str(val).strip()
    return portal


def _has_search_criteria(filters: dict, multi_codes: bool) -> bool:
    """True when enough filters are present to run a targeted search."""
    if filters.get("customer_code"):
        return True
    if any(filters.get(k) for k in _SEARCH_FILTER_PORTAL_KEYS):
        return True
    return False


def search_workorders(
    user_id: str,
    session: int,
    customer_codes: "str | list",
    search_filters: dict,
) -> dict:
    """QueryCustomerOrders with CustCall, SiteID, Model, Serial, etc."""
    ensure_env()
    filters = _normalize_search_filters(search_filters)
    if not _has_search_criteria(filters, len(_normalize_customer_codes(customer_codes)) > 1):
        return {
            "success": False,
            "error": (
                "Provide at least one search filter: customer call number, site ID, "
                "model, serial, or WO number."
            ),
            "orders": [],
        }

    codes = _normalize_customer_codes(customer_codes)
    if not codes:
        return {"success": False, "error": "No customer codes available.", "orders": []}

    target = (filters.get("customer_code") or "").strip()
    if target:
        allowed = {c.upper() for c in codes}
        if target.upper() not in allowed:
            return {
                "success": False,
                "error": f"Customer code {target} is not in your authorized customer list.",
                "orders": [],
            }
        codes = [target]

    wo_status = filters.get("wo_status") or "A"
    days_back = filters.get("days_back") or (90 if wo_status != "O" else 30)
    since = (
        datetime.date.today() - datetime.timedelta(days=days_back)
    ).strftime("%Y%m%d")
    portal_filters = _search_portal_filters(filters)

    all_orders: list[dict] = []
    for code in codes:
        all_orders.extend(
            _query_orders_for_code(
                user_id, session, code, since, wo_status, portal_filters
            )
        )

    return {"success": True, "orders": all_orders, "count": len(all_orders)}


def list_workorders(
    user_id: str,
    session: int,
    customer_codes: "str | list",
    days_back: int = 30,
    status: str = "O",
) -> dict:
    ensure_env()
    since = (
        datetime.date.today() - datetime.timedelta(days=days_back)
    ).strftime("%Y%m%d")

    codes = _normalize_customer_codes(customer_codes)

    if not codes:
        return {"success": False, "error": "No customer codes available.", "orders": []}

    all_orders: list[dict] = []
    for code in codes:
        all_orders.extend(_query_orders_for_code(user_id, session, code, since, status))

    return {"success": True, "orders": all_orders, "count": len(all_orders)}


def get_workorder(user_id: str, session: int, wo_number: str) -> dict:
    ensure_env()
    gts = GTService()
    detail: dict = {}
    api_error: str = ""
    try:
        resp = gts.GetCallDetailV3(user_id, session, Ordernum=wo_number)
        if resp.success:
            items = resp.results()
            if items:
                detail = _to_dict(items[0])
        else:
            api_error = f"RC={getattr(resp, 'RC', '?')} {getattr(resp, 'ResultMsg', '')}"
    except Exception as exc:
        api_error = str(exc)

    remarks: list = []
    try:
        resp = gts.GetCallRemarks(user_id, session, wo_number)
        if resp.success:
            remarks = [_to_dict(r) for r in resp.results()]
    except Exception:
        pass

    return {
        "success": bool(detail),
        "detail": detail,
        "remarks": remarks,
        "error": api_error,
    }


def get_workorder_full(
    user_id: str,
    session: int,
    wo_number: str,
    customer_codes: "str | list | None" = None,
) -> dict:
    """Detail + remarks + parts + labor; optional customer scope check."""
    result = get_workorder(user_id, session, wo_number)
    if not result["success"]:
        return {**result, "parts": [], "labor": []}

    if customer_codes is not None:
        try:
            _assert_wo_in_scope(result["detail"], customer_codes)
        except ValueError as exc:
            return {
                "success": False,
                "detail": {},
                "remarks": [],
                "parts": [],
                "labor": [],
                "error": str(exc),
            }

    gts = GTService()
    order_no = (result["detail"].get("ordernum") or wo_number or "").strip()
    csr = (result["detail"].get("CSR") or "").strip()

    parts: list[dict] = []
    labor: list[dict] = []
    try:
        parts = _get_call_parts(gts, user_id, session, order_no)
    except Exception:
        pass
    try:
        labor = _safe_wo_results(gts.QueryLaborItems(user_id, session, order_no, csr))
    except Exception:
        pass

    return {**result, "parts": parts, "labor": labor}


def _wo_preflight_scope(
    user_id: str,
    session: int,
    wo_number: str,
    customer_codes: "str | list",
) -> dict:
    """Load WO detail and enforce customer scope before focused reads."""
    result = get_workorder(user_id, session, wo_number)
    if not result["success"]:
        err = result.get("error") or "Work order not found."
        return {"success": False, "detail": {}, "error": err}
    try:
        _assert_wo_in_scope(result["detail"], customer_codes)
    except ValueError as exc:
        return {"success": False, "detail": {}, "error": str(exc)}
    return {"success": True, "detail": result["detail"], "error": ""}


def _order_no_from_detail(detail: dict, wo_number: str) -> str:
    return (detail.get("ordernum") or wo_number or "").strip()


def _site_params_from_detail(detail: dict) -> tuple[str, str]:
    cust = (detail.get("custcode") or detail.get("CustCode") or "").strip()
    site_id = (
        detail.get("siteID")
        or detail.get("SiteID")
        or detail.get("siteid")
        or ""
    )
    return cust, str(site_id).strip()


def get_workorder_parts(
    user_id: str,
    session: int,
    wo_number: str,
    customer_codes: "str | list",
) -> dict:
    """GetCallParts with scope preflight."""
    ensure_env()
    pre = _wo_preflight_scope(user_id, session, wo_number, customer_codes)
    if not pre["success"]:
        return {"success": False, "parts": [], "detail": {}, "error": pre["error"]}
    order_no = _order_no_from_detail(pre["detail"], wo_number)
    try:
        parts = _get_call_parts(GTService(), user_id, session, order_no)
    except Exception as exc:
        return {"success": False, "parts": [], "detail": pre["detail"], "error": str(exc)}
    return {"success": True, "parts": parts, "detail": pre["detail"], "error": ""}


def get_workorder_part_line(
    user_id: str,
    session: int,
    wo_number: str,
    line_no: int,
    customer_codes: "str | list",
) -> dict:
    """GetCallPartDetail with scope preflight."""
    ensure_env()
    pre = _wo_preflight_scope(user_id, session, wo_number, customer_codes)
    if not pre["success"]:
        return {"success": False, "part_line": {}, "detail": {}, "error": pre["error"]}
    order_no = _order_no_from_detail(pre["detail"], wo_number)
    try:
        resp = GTService().GetCallPartDetail(user_id, session, order_no, int(line_no))
        if resp.success or getattr(resp, "RC", -1) == 2:
            items = resp.results()
            part_line = _to_dict(items[0]) if items else {}
            if not part_line and getattr(resp, "RC", -1) != 2:
                return {
                    "success": False,
                    "part_line": {},
                    "detail": pre["detail"],
                    "error": getattr(resp, "ResultMsg", "Part line not found."),
                }
            return {
                "success": True,
                "part_line": part_line,
                "detail": pre["detail"],
                "error": "",
            }
        return {
            "success": False,
            "part_line": {},
            "detail": pre["detail"],
            "error": f"RC={getattr(resp, 'RC', '?')} {getattr(resp, 'ResultMsg', '')}",
        }
    except Exception as exc:
        return {"success": False, "part_line": {}, "detail": pre["detail"], "error": str(exc)}


def get_workorder_labor(
    user_id: str,
    session: int,
    wo_number: str,
    customer_codes: "str | list",
) -> dict:
    """QueryLaborItems with scope preflight."""
    ensure_env()
    pre = _wo_preflight_scope(user_id, session, wo_number, customer_codes)
    if not pre["success"]:
        return {"success": False, "labor": [], "detail": {}, "error": pre["error"]}
    order_no = _order_no_from_detail(pre["detail"], wo_number)
    csr = (pre["detail"].get("CSR") or "").strip()
    try:
        labor = _safe_wo_results(
            GTService().QueryLaborItems(user_id, session, order_no, csr)
        )
    except Exception as exc:
        return {"success": False, "labor": [], "detail": pre["detail"], "error": str(exc)}
    return {"success": True, "labor": labor, "detail": pre["detail"], "error": ""}


def get_workorder_labor_activities(
    user_id: str,
    session: int,
    wo_number: str,
    customer_codes: "str | list",
) -> dict:
    """QueryLaborActivities with scope preflight."""
    ensure_env()
    pre = _wo_preflight_scope(user_id, session, wo_number, customer_codes)
    if not pre["success"]:
        return {"success": False, "labor_activities": [], "detail": {}, "error": pre["error"]}
    order_no = _order_no_from_detail(pre["detail"], wo_number)
    try:
        activities = _safe_wo_results(
            GTService().QueryLaborActivities(user_id, session, order_no)
        )
    except Exception as exc:
        return {
            "success": False,
            "labor_activities": [],
            "detail": pre["detail"],
            "error": str(exc),
        }
    return {
        "success": True,
        "labor_activities": activities,
        "detail": pre["detail"],
        "error": "",
    }


def get_workorder_site(
    user_id: str,
    session: int,
    wo_number: str,
    customer_codes: "str | list",
) -> dict:
    """GetSiteDetail for the WO's customer/site with scope preflight."""
    ensure_env()
    pre = _wo_preflight_scope(user_id, session, wo_number, customer_codes)
    if not pre["success"]:
        return {"success": False, "site": {}, "detail": {}, "error": pre["error"]}
    cust, site_id = _site_params_from_detail(pre["detail"])
    if not cust or not site_id:
        return {
            "success": False,
            "site": {},
            "detail": pre["detail"],
            "error": "Work order has no site ID for a site lookup.",
        }
    try:
        resp = GTService().GetSiteDetail(
            user_id, session, CustCode=cust, SiteID=site_id
        )
        if resp.success or getattr(resp, "RC", -1) == 2:
            site = {
                "SiteID": getattr(resp, "SiteID", site_id) or site_id,
                "CustCode": getattr(resp, "CustCode", cust) or cust,
                "EndCust": getattr(resp, "EndCust", "") or "",
                "City": getattr(resp, "City", "") or "",
                "State": getattr(resp, "State", "") or "",
                "Zip": getattr(resp, "Zip", "") or "",
                "Country": getattr(resp, "Country", "") or "",
                "SiteContact": getattr(resp, "SiteContact", "") or "",
                "SitePhone": getattr(resp, "SitePhone", "") or "",
                "StreetAddress": getattr(resp, "StreetAddress", "") or "",
                "AddtlAddr": getattr(resp, "AddtlAddr", "") or "",
            }
            return {"success": True, "site": site, "detail": pre["detail"], "error": ""}
        return {
            "success": False,
            "site": {},
            "detail": pre["detail"],
            "error": f"RC={getattr(resp, 'RC', '?')} {getattr(resp, 'ResultMsg', '')}",
        }
    except Exception as exc:
        return {"success": False, "site": {}, "detail": pre["detail"], "error": str(exc)}


def _map_create_fields(fields: dict) -> dict:
    """Map friendly field names → GTCallInterface API parameter names."""
    customer_code = fields.get("Customer Code", "")
    site_id = fields.get("Site ID", "")
    no_asset = not site_id
    return {
        "WONumber": "",
        "WOAltnum": fields.get("Customer Call Number", ""),
        "RootCedic": "ASDS-" + customer_code,
        "NoAsset": no_asset,
        "WOSystem": fields.get("Product Reference", ""),
        "SKU": "",
        "WOSite": site_id if not no_asset else "",
        "WOSerial": fields.get("Serial", ""),
        "WOModel": fields.get("Product Reference", ""),
        "WOCtName": fields.get("End User") or fields.get("Contact Name", ""),
        "WOAddress": fields.get("Customer Address", ""),
        "WOAddress1": "",
        "WOCity": fields.get("Customer City", ""),
        "WOState": fields.get("Customer State", ""),
        "WOZip": fields.get("Customer Postal Code", ""),
        "WOCountry": fields.get("Customer Country", "US"),
        "WOConct": fields.get("Contact Name", ""),
        "WOPhone": fields.get("Contact Phone", ""),
        "EmailAddr": fields.get("Contact Email", ""),
        "Cont140": False,
        "ImmedFlag": False,
        "ReqDate": "",
        "ReqTime": "",
        "PartFlag": False,
        "CovCode": "",
        "WOClone": False,
        "AltRefNum": "",
        "NSSArea": 0,
        "SignoffReq": 0,
        "WOReason": "",
        "ModelOverride": "",
        "VendorNum": "",
        "SkillModel": "",
        "AvgRepairTime": 0,
        "AltRefNum2": "",
        "ClonedWO": "",
        "ActionGrp": "",
        "SchStartDT": "",
        "SchStartTM": "",
        "SchEndDT": "",
        "SchEndTM": "",
        "PO": "",
        "EntryDT": "",
        "EntryTM": "",
        "subclass": "",
        "WOAltPhone": fields.get("Contact Phone 2", ""),
        "WOAltContact": "",
        "WOAltContact1stPhone": "",
        "woAltContact2ndPhone": "",
        "SubDiv": "",
        "RC": 0,
        "ResultMsg": "",
    }


_ADDRESS_KEYWORDS = ("address", "site", "location", "zip", "postal", "city", "state")


def _is_address_error(msg: str) -> bool:
    lower = (msg or "").lower()
    return any(kw in lower for kw in _ADDRESS_KEYWORDS)


_STATE_NAMES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}


def _split_city_state_zip(out: dict) -> None:
    """Split a combined location dumped into Customer City into its parts.

    Handles "Round Rock, Texas 78682", "Round Rock, Texas, 78682",
    and "Round Rock, Texas" — only filling State/Postal when still empty.
    """
    city = out.get("Customer City")
    if not isinstance(city, str) or not city.strip():
        return
    # City, State ZIP  /  City, State, ZIP
    m = re.match(
        r"^\s*(?P<city>.+?),\s*(?P<state>[A-Za-z][A-Za-z .]+?)\s*,?\s*(?P<zip>\d{5}(?:-\d{4})?)\s*$",
        city,
    )
    if m:
        out["Customer City"] = m.group("city").strip()
        if not out.get("Customer State"):
            out["Customer State"] = m.group("state").strip()
        if not out.get("Customer Postal Code"):
            out["Customer Postal Code"] = m.group("zip").strip()
        return
    # City, State (no zip)
    if not out.get("Customer State"):
        m = re.match(r"^\s*(?P<city>.+?),\s*(?P<state>[A-Za-z][A-Za-z .]{1,})\s*$", city)
        if m:
            out["Customer City"] = m.group("city").strip()
            out["Customer State"] = m.group("state").strip()


def _normalize_fields(fields: dict) -> dict:
    """Strip whitespace, normalize phone numbers, and abbreviate state names."""
    out = {}
    for key, val in fields.items():
        if isinstance(val, str):
            val = val.strip()
        out[key] = val
    _split_city_state_zip(out)
    for phone_key in ("Contact Phone", "Contact Phone 2"):
        if out.get(phone_key):
            out[phone_key] = re.sub(r"[^\d+]", "", out[phone_key])
    if out.get("Customer State"):
        abbrev = _STATE_NAMES.get(out["Customer State"].lower())
        if abbrev:
            out["Customer State"] = abbrev
    return out


def create_fields_fingerprint(fields: dict) -> str:
    """Stable hash of normalized create fields for idempotency checks."""
    payload = json.dumps(_normalize_fields(dict(fields or {})), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _extract_order_num(resp) -> str:
    """Try every plausible attribute/key name the WWTS response might use."""
    for name in ("OrderNum", "WONumber", "ordernum", "wonumber", "order_num", "wo_number"):
        val = getattr(resp, name, None)
        if val and str(val).strip():
            return str(val).strip()
    if hasattr(resp, "get"):
        for name in ("OrderNum", "WONumber", "ordernum", "wonumber"):
            val = resp.get(name, "")
            if val and str(val).strip():
                return str(val).strip()
    return ""


def _attempt_create(user_id: str, session: int, fields: dict) -> dict:
    try:
        api_params = _map_create_fields(fields)
        resp = GTCallInterface().request_for_open(user_id, session, **api_params)
        return {
            "success": resp.RC == 0,
            "RC": resp.RC,
            "ResultMsg": resp.ResultMsg,
            "OrderNum": _extract_order_num(resp),
            "session_expired": is_session_expired_error(getattr(resp, "ResultMsg", "")),
        }
    except Exception as exc:
        return {
            "success": False,
            "RC": -1,
            "ResultMsg": str(exc),
            "OrderNum": "",
            "session_expired": is_session_expired_error(exc),
        }


def create_workorder(user_id: str, session: int, fields: dict) -> dict:
    ensure_env()
    return _attempt_create(user_id, session, _normalize_fields(fields))
