"""Regression tests for the diagnose-session bug fixes.

Per project rule: no calls are mocked except the voice layer. The session-expiry
test runs against the REAL (now-expired) WWTS session stored at login time, which
is exactly the failure state the user hit.
"""
import sys

sys.path.insert(0, "D:/real-time-voice/wwts-agent")
sys.path.insert(0, "D:/real-time-voice/server")

from wwts_agent import api
from wwts_agent.nodes.converse import (
    _detect_get_focus,
    _normalize_create_fields,
    _missing_create_fields,
    converse,
)
from wwts_agent.nodes.execute import (
    _address_error_recovery,
    _build_remarks_speak,
    _session_expired_state,
    execute,
)


FAKE_CTX = {
    "wwts_session": 9999,
    "customer_codes": [{"code": "DELLQXS", "name": "Dell QXS"}],
    "authorized_functions": ["RequestForOpen"],
}


# ── FIX 3: location given as one phrase is split into city/state/postal ────────
def test_location_phrase_with_zip_is_split():
    fields = _normalize_create_fields({"Customer City": "Round Rock, Texas 78682"})
    assert fields["Customer City"] == "Round Rock"
    assert fields["Customer State"] == "Texas"
    assert fields["Customer Postal Code"] == "78682"


def test_location_phrase_with_comma_zip_is_split():
    fields = _normalize_create_fields({"Customer City": "Round Rock, Texas, 78682"})
    assert fields["Customer City"] == "Round Rock"
    assert fields["Customer State"] == "Texas"
    assert fields["Customer Postal Code"] == "78682"


def test_location_split_completes_create_fields():
    fields = _normalize_create_fields(
        {
            "Customer Code": "DELLQXS",
            "Product Reference": "BDQ",
            "Contact Name": "Rachit Gandhi",
            "Contact Phone": "9650470567",
            "Customer City": "Round Rock, Texas 78682",
        }
    )
    assert _missing_create_fields(fields, has_customer_code=True) == []


def test_api_normalize_fields_splits_city_state_zip():
    out = api._normalize_fields({"Customer City": "Austin, Texas 73301"})
    assert out["Customer City"] == "Austin"
    assert out["Customer State"] == "TX"  # abbreviated downstream
    assert out["Customer Postal Code"] == "73301"


# ── FIX 4: free-text close reason is accepted, no re-ask loop ───────────────────
def test_free_text_close_reason_accepted():
    # No wwts_session in context -> preflight is skipped -> reaches confirming_close.
    state = converse(
        {
            "stage": "collecting_close_reason",
            "intent": "close_wo",
            "wo_number": "WA01050002",
            "wo_detail": {"custcode": "DELLQXS", "vstatus": "DS"},
            "close_fields": {},
            "user_message": "The work is completed.",
            "context": {"customer_codes": [{"code": "DELLQXS"}]},
            "messages": [],
        }
    )
    assert state["stage"] == "confirming_close"
    assert state["close_fields"]["Close Reason"] == "The work is completed"


def test_close_reason_still_rejects_bare_no():
    state = converse(
        {
            "stage": "collecting_close_reason",
            "intent": "close_wo",
            "wo_number": "WA01050002",
            "wo_detail": {"custcode": "DELLQXS", "vstatus": "DS"},
            "close_fields": {},
            "user_message": "no",
            "context": {"customer_codes": [{"code": "DELLQXS"}]},
            "messages": [],
        }
    )
    assert state["stage"] == "collecting_close_reason"


# ── FIX 5: remarks read intent + spoken summary ────────────────────────────────
def test_remarks_keyword_detected_as_focus():
    assert _detect_get_focus("can you tell me the remarks for this work order") == "remarks"
    assert _detect_get_focus("what is the activity history") == "remarks"
    # "add a remark" is a write, not a read focus
    assert _detect_get_focus("add a remark that the part shipped") != "remarks"


def test_remarks_speak_lists_latest_remark():
    speak = _build_remarks_speak(
        {"ordernum": "WA01050002"},
        [
            {"author": "TECH1", "remdata": "Arrived on site"},
            {"author": "TECH2", "remdata": "Replaced unit"},
        ],
        "WA01050002",
    )
    assert "2 remarks" in speak
    assert "Replaced unit" in speak


def test_remarks_speak_handles_empty():
    speak = _build_remarks_speak({"ordernum": "WA01050002"}, [], "WA01050002")
    assert "no remarks" in speak.lower()


def test_find_remarks_on_known_wo_is_not_a_search(monkeypatch):
    """'find the remarks on this work order' must read the WO, not loop on search."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # exercise fallback routing
    state = converse(
        {
            "stage": "done",
            "intent": "get_wo",
            "wo_number": "WA01050002",
            "context": FAKE_CTX,
            "messages": [],
            "user_message": "Can you find the remarks on this work order?",
        }
    )
    assert state["stage"] == "executing_get"
    assert state["intent"] == "get_wo"
    assert state.get("wo_get_focus") == "remarks"


# ── FIX 1: session-expiry classifier + friendly surfacing ───────────────────────
def _full_loc_fields():
    return {
        "Customer Code": "DELLQXS",
        "Product Reference": "BDQ",
        "Contact Name": "Rachit Gandhi",
        "Contact Phone": "9650470567",
        "Customer City": "Round Rock",
        "Customer State": "TX",
        "Customer Postal Code": "78682",
    }


# ── Address-validation failure must escalate to street, not loop on city/state/zip
def test_address_failure_with_location_asks_for_street():
    fields = _full_loc_fields()
    cleaned, msg = _address_error_recovery(fields, "The address information is invalid.")
    low = msg.lower()
    assert "street" in low
    # must NOT re-ask for the exact fields that just failed
    assert "city, state, and zip" not in low or "street address" in low
    assert cleaned.get("Customer City") == "Round Rock"  # keeps what we had


def test_address_failure_after_street_does_not_repeat():
    fields = {**_full_loc_fields(), "Customer Address": "123 Main St"}
    _, msg = _address_error_recovery(fields, "Address validation failed.")
    low = msg.lower()
    assert "still didn't validate" in low
    assert "site id" in low  # offers the alternative path


def test_address_failure_with_bad_site_drops_site():
    fields = {"Customer Code": "DELLQXS", "Product Reference": "BDQ", "Site ID": "BOGUS9"}
    cleaned, msg = _address_error_recovery(fields, "Site not found.")
    assert "Site ID" not in cleaned
    assert "BOGUS9" in msg


def test_address_failure_surfaces_real_reason():
    _, msg = _address_error_recovery(_full_loc_fields(), "Zip code does not match city")
    assert "Zip code does not match city" in msg


# ── Remark write uses the correct WWTS RemarkNew field names ───────────────────
def test_remark_params_use_worem_not_remdata():
    params = api._remark_new_params(
        "WA01050002", "Tested by support agent", "GEN",
        {"ordernum": "WA01050002", "custcall": "CALL-77", "custcode": "DELLQXS"},
    )
    assert params["WORem"] == "Tested by support agent"  # the actual remark field
    assert params["WONumber"] == "WA01050002"
    assert params["WOAltNum"] == "CALL-77"                # populated -> no "woaltnum invalid"
    assert params["RootCedic"] == "ASDS-DELLQXS"          # populated -> no "rootcedic invalid"
    assert "RemData" not in params                         # the bogus field is gone
    assert "RemType" not in params
    assert "WOMajAct" not in params                        # GEN default is omitted


def test_remark_params_rootcedic_prefers_explicit():
    params = api._remark_new_params("WA1", "note text here", "GEN", {"rootcedic": "XYZ-1", "custcode": "DELLQXS"})
    assert params["RootCedic"] == "XYZ-1"


def test_remark_params_real_major_activity_passed():
    params = api._remark_new_params("WA1", "note text here", "ESC", None)
    assert params["WOMajAct"] == "ESC"
    assert "WOAltNum" not in params  # no detail -> omitted, not blank
    assert "RootCedic" not in params


# ── Remark text extraction must not capture the WO-reference phrase ─────────────
def test_remark_extractor_rejects_wo_reference():
    from wwts_agent.nodes.converse import _extract_remark_text_from_text

    assert _extract_remark_text_from_text("Hey, can you add a remark to a work order?") is None
    assert _extract_remark_text_from_text("add a remark to this work order") is None
    # real content still extracts
    assert _extract_remark_text_from_text("add a remark that the part shipped") == "the part shipped"


def test_collecting_remark_overwrites_stale_text():
    """User's answer to 'what remark?' replaces a stale value from an earlier turn."""
    state = converse(
        {
            "stage": "collecting_remark_text",
            "intent": "add_wo_remark",
            "wo_number": "WA01050002",
            "remark_text": "to a work order?",  # stale garbage from turn 1
            "user_message": "This remark has been added by the WWTS support agent.",
            "context": {"customer_codes": [{"code": "DELLQXS"}]},  # no session -> skip live validate
            "messages": [],
        }
    )
    assert "support agent" in (state.get("remark_text") or "")
    assert "work order" not in (state.get("remark_text") or "").lower()


# ── Lookback change re-runs the search with a wider window ─────────────────────
def test_detect_days_back_handles_loose_phrasing():
    from wwts_agent.nodes.converse import _detect_days_back

    assert _detect_days_back("Increase the loopback to about 8 months.") == 240
    assert _detect_days_back("increase lookback to 40 days") == 40
    assert _detect_days_back("No, increase look back 2 to 40 days.") == 40
    assert _detect_days_back("about eight months") == 240
    assert _detect_days_back("two years") == 730


def test_lookback_change_reruns_search(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # deterministic fallback path
    state = converse(
        {
            "stage": "done",
            "intent": "search_wo",
            "search_filters": {"model": "BDQ", "wo_status": "O"},
            "wo_status": "O",
            "wo_days_back": 30,
            "user_message": "Increase the lookback to about 8 months.",
            "context": {"customer_codes": [{"code": "DELLQXS"}]},
            "messages": [],
        }
    )
    assert state["stage"] == "executing_list"
    assert state["intent"] == "search_wo"
    assert state["search_filters"]["days_back"] == 240
    assert state["search_filters"]["model"] == "BDQ"  # prior filter preserved


def test_session_expired_classifier():
    assert api.is_session_expired_error("Expecting value: line 1 column 1 (char 0)")
    assert api.is_session_expired_error("The request is invalid.")
    assert not api.is_session_expired_error("Customer code FOO is not authorized")


def test_create_surfaces_session_expiry_not_raw_parse_error():
    """Real-API: the stored dpscript session is expired -> friendly re-login msg."""
    import database  # noqa: F401  (ensures server path wired)
    from wwts_session_store import get_login_session

    stored = get_login_session(45270896)
    if not stored:
        import pytest

        pytest.skip("no stored dpscript session to exercise expiry against")

    state = execute(
        {
            "stage": "executing_create",
            "user_id": stored["user_id"],
            "thread_id": "t-expiry",
            "create_fields": {
                "Customer Code": "DELLQXS",
                "Product Reference": "BDQ",
                "Contact Name": "Rachit Gandhi",
                "Contact Phone": "9650470567",
                "Customer City": "Round Rock",
                "Customer State": "TX",
                "Customer Postal Code": "78682",
            },
            "context": {
                "wwts_session": stored["wwts_session"],
                "customer_codes": stored["customer_codes"],
                "authorized_functions": stored["authorized_functions"],
            },
        }
    )
    assert state.get("session_expired") is True
    assert "expired" in state["speak"].lower()
    assert "expecting value" not in state["speak"].lower()
