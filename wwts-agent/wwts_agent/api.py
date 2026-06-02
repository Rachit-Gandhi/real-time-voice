"""Thin wrappers around portals.wwits API calls that return plain dicts."""
import datetime
import re
from dataclasses import asdict

from portals.wwits.apis.rest_services import GTCallInterface, GTService
from portals.wwits.environment import Environment, wwits_env

_DEFAULT_ENV = "QA"
_DEFAULT_SRC = "WMP"


def ensure_env() -> None:
    if wwits_env.is_init:
        return
    try:
        Environment(environment=_DEFAULT_ENV, source=_DEFAULT_SRC,
                    config_file=wwits_env.config, path="")
    except Exception:
        pass


def _to_dict(obj) -> dict:
    try:
        return asdict(obj)
    except Exception:
        return vars(obj) if hasattr(obj, "__dict__") else {}


def _query_orders_for_code(
    user_id: str, session: int, code: str, since: str, status: str
) -> list[dict]:
    try:
        resp = GTService().QueryCustomerOrders(
            user_id, session, custcode=code, opensince=since, wostatus=status
        )
        # RC=2 means "no records found" in the WWTS API — not a system error
        if resp.success or getattr(resp, "RC", -1) == 2:
            results = resp.results()
            return [_to_dict(o) for o in results] if results else []
    except Exception:
        pass
    return []


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

    # Normalise to a list of code strings
    if isinstance(customer_codes, str):
        codes = [customer_codes] if customer_codes else []
    else:
        # Each entry may be {"code": "ACME", "name": "..."} or a plain string
        codes = [
            c["code"] if isinstance(c, dict) else c
            for c in customer_codes
            if c
        ]

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


def _normalize_fields(fields: dict) -> dict:
    """Strip whitespace, normalize phone numbers, and abbreviate state names."""
    out = {}
    for key, val in fields.items():
        if isinstance(val, str):
            val = val.strip()
        out[key] = val
    city = out.get("Customer City")
    if isinstance(city, str) and not out.get("Customer State"):
        match = re.match(r"^\s*(?P<city>.+?),\s*(?P<state>[A-Za-z][A-Za-z .]{1,})\s*$", city)
        if match:
            out["Customer City"] = match.group("city").strip()
            out["Customer State"] = match.group("state").strip()
    for phone_key in ("Contact Phone", "Contact Phone 2"):
        if out.get(phone_key):
            out[phone_key] = re.sub(r"[^\d+]", "", out[phone_key])
    if out.get("Customer State"):
        abbrev = _STATE_NAMES.get(out["Customer State"].lower())
        if abbrev:
            out["Customer State"] = abbrev
    return out


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
        }
    except Exception as exc:
        return {"success": False, "RC": -1, "ResultMsg": str(exc), "OrderNum": ""}


def create_workorder(user_id: str, session: int, fields: dict) -> dict:
    ensure_env()
    return _attempt_create(user_id, session, _normalize_fields(fields))
