"""Offline tests for the scripted laptop-troubleshooting support flow.

No network / no OpenAI key required: the troubleshoot sub-flow is an early
return in converse() (no LLM), troubleshoots fall back to the bundled FAQ, and
the product lookup degrades to "" without a session.
"""
import os

import pytest

os.environ.pop("OPENAI_API_KEY", None)

from wwts_agent import faq, api
from wwts_agent.nodes import converse as C
from wwts_agent.nodes import execute as E

CTX = {"customer_codes": [{"code": "DELLQXS", "name": "Dell"}]}  # single → auto customer code


def step(state, msg):
    s = dict(state)
    s["context"] = CTX
    s["user_message"] = msg
    s.setdefault("messages", [])
    return C.converse(s)


def test_faq_matcher():
    assert faq.match_faq("my laptop won't turn on, totally dead")["id"] == "laptop_no_power"
    assert faq.match_faq("it keeps overheating and the fan is loud")["id"] == "laptop_overheating"
    assert faq.match_faq("how do I reset my password") is None


def test_trigger_detection():
    assert C._detect_troubleshoot_intent("my dell laptop won't turn on")
    assert not C._detect_troubleshoot_intent("I want to create a work order")


def test_issue_first_path_through_to_create():
    s = step({"stage": "greeting", "intent": None}, "my dell laptop won't power on")
    assert s["stage"] == "ts_collecting_name"
    assert s.get("ts_issue")

    s = step(s, "Rachit")
    assert s.get("ts_name") == "Rachit"
    assert s["stage"] == "ts_collecting_product"  # concrete issue already known

    s = step(s, "BDQ")
    # Issue is already concrete ("won't power on") → straight to troubleshooting.
    assert s["stage"] == "ts_troubleshooting"
    assert s.get("ts_product_ref") == "BDQ"
    troubleshoots = s.get("ts_troubleshoots") or []
    assert 1 <= len(troubleshoots) <= C._TS_MAX_TROUBLESHOOTS
    assert sum(len(t["steps"]) for t in troubleshoots) <= 10
    assert s.get("ts_executed") == 1

    s = step(s, "no, still dead")
    assert s.get("ts_executed") == 2 and s["stage"] == "ts_troubleshooting"

    s = step(s, "no")
    assert s["intent"] == "create_wo"
    assert s.get("pending_troubleshoot") is True
    cf = s.get("create_fields") or {}
    assert cf.get("Contact Name") == "Rachit"
    assert cf.get("Product Reference") == "BDQ"
    assert s.get("ts_resolved") is False


def test_name_first_then_confirm_then_resolved():
    s = step({"stage": "greeting", "intent": None}, "hello")
    assert s["stage"] == "ts_collecting_name"
    s = step(s, "I'm Rachit")
    assert s["stage"] == "ts_confirm_issue" and s.get("ts_name") == "Rachit"
    s = step(s, "yes")
    assert s["stage"] == "ts_collecting_product"
    s = step(s, "BDQ")
    # Lookup empty + no concrete symptom yet → one combined device/issue question.
    assert s["stage"] == "ts_collecting_issue"
    s = step(s, "it overheats and shuts down")
    assert s["stage"] == "ts_troubleshooting"
    s = step(s, "yes that fixed it")
    assert s["intent"] == "create_wo" and s.get("ts_resolved") is True


def test_decline_routes_to_menu():
    s = step({"stage": "greeting", "intent": None}, "hi")
    s = step(s, "Rachit")
    s = step(s, "no")
    assert s["stage"] == "intent" and s["intent"] is None


def test_list_request_not_hijacked():
    s = step({"stage": "greeting", "intent": None}, "show my open work orders")
    assert s.get("intent") != "troubleshoot"


def test_greeting_then_wo_command_bails_out():
    # "hi" opens the support flow (asks for name)...
    s = step({"stage": "greeting", "intent": None}, "hi")
    assert s["stage"] == "ts_collecting_name"
    # ...but a real work-order command on the next turn must not be eaten as a name.
    s = step(s, "how many open work orders are there?")
    assert s.get("intent") != "troubleshoot"
    assert not str(s.get("stage", "")).startswith("ts_")


def test_vague_issue_asks_for_concrete_symptom():
    # Vague issue + empty lookup → keep asking until a real symptom is given.
    s = step({"stage": "greeting", "intent": None}, "hi")
    s = step(s, "Rachit")
    assert s["stage"] == "ts_confirm_issue"
    s = step(s, "yes I'm facing some issues")          # vague
    assert s["stage"] == "ts_collecting_product"
    s = step(s, "BDQ")                                  # lookup empty (no session)
    assert s["stage"] == "ts_collecting_issue"          # combined device/issue ask
    s = step(s, "a Dell Latitude laptop")               # device only, no symptom
    assert s["stage"] == "ts_collecting_issue"          # still need the symptom
    assert s.get("ts_device")                           # but device was captured
    s = step(s, "it won't power on at all")             # concrete now
    assert s["stage"] == "ts_troubleshooting"


def test_product_ref_extraction_skips_filler_words():
    # Regression: "reference for the device is BDQ" must yield BDQ, not "FOR".
    assert C._extract_product_ref("The product reference for the device is BDQ.") == "BDQ"
    assert C._extract_product_ref("product reference BDQ") == "BDQ"
    assert C._extract_product_ref("BDQ") == "BDQ"


def test_device_extraction():
    assert C._extract_device("technical difficulty with my HP Elite book").lower().startswith("hp")
    assert C._extract_device("it's a Dell laptop").lower().startswith("dell")
    assert C._extract_device("my printer is broken") == "printer"


def test_read_remarks_is_not_a_write():
    # Regression: "logged" must not trigger the 'log' add-remark verb.
    assert C._detect_remark_intent("add a remark that the part shipped") is True
    assert C._detect_remark_intent("read me the two logged remarks") is False
    assert C._detect_remark_intent("can you read me the user comment") is False
    assert C._detect_get_focus("read me the two logged remarks") == "remarks"


def test_status_after_create_does_not_reask_number():
    # Simulate post-create state: WO in context, stage done.
    s = step({"stage": "done", "intent": None, "wo_number": "WA06020003"},
             "what is the status right now?")
    assert s["stage"] == "executing_get"
    assert s.get("wo_number") == "WA06020003"


def test_remarks_view_surfaces_bot_comments():
    remarks = [
        {"author": "sys", "remdata": ""},
        {"author": "acesus", "remdata": "customer using ePSA tool"},
        {"author": "DPSCRIPT", "remdata": "User Comment (caller: Rachit): won't power on"},
        {"author": "DPSCRIPT", "remdata": "AI Comment — analysis for Dell Latitude. Outcome: not resolved."},
    ]
    msg, speak = E._remarks_view("WA06020003", remarks, want_all=False)
    assert "User Comment" in speak and "AI Comment" in speak
    assert "2 logged remark" in speak
    # blank row dropped → 3 real remarks, not 4
    assert "3 remark(s)" in msg


def test_llm_extraction_lets_caller_volunteer_everything(monkeypatch):
    # With the model understanding free text, giving the product ref + issue at the
    # "technical difficulty?" step should skip straight to troubleshooting.
    monkeypatch.setattr(C, "_ts_extract", lambda messages, known: {
        "name": "Chandler", "product_reference": "BDQ",
        "device": "HP EliteBook laptop", "issue": "overheats, hits 100C, work stutters",
        "has_symptom": True, "declines_help": False,
    })
    out = C.converse({
        "stage": "ts_confirm_issue", "intent": "troubleshoot", "context": CTX,
        "ts_name": "Chandler", "messages": [],
        "user_message": "yes, my HP EliteBook (BDQ) overheats to 100C and stutters",
    })
    assert out["stage"] == "ts_troubleshooting"
    assert out.get("ts_product_ref") == "BDQ"
    assert out.get("ts_device")


def test_llm_extraction_product_ref_not_a_filler_word(monkeypatch):
    # The model returns the real code even though regex once grabbed "FOR".
    monkeypatch.setattr(C, "_ts_extract", lambda messages, known: {
        "name": "Chandler", "product_reference": "BDQ", "has_symptom": False,
    })
    out = C.converse({
        "stage": "ts_collecting_product", "intent": "troubleshoot", "context": CTX,
        "ts_name": "Chandler", "messages": [],
        "user_message": "the product reference for the device is BDQ",
    })
    assert out.get("ts_product_ref") == "BDQ"
    assert out["stage"] == "ts_collecting_issue"  # now needs the symptom


def test_declines_help_routes_to_menu(monkeypatch):
    monkeypatch.setattr(C, "_ts_extract", lambda messages, known: {"declines_help": True})
    out = C.converse({
        "stage": "ts_confirm_issue", "intent": "troubleshoot", "context": CTX,
        "ts_name": "Chandler", "messages": [], "user_message": "no, I'm good thanks",
    })
    assert out["stage"] == "intent" and out["intent"] is None


def test_canonicalize_customer_code():
    codes = [{"code": "DELLQXS", "name": "Dell"}]
    assert C._canonicalize_customer_code("del Q X S", codes) == "DELLQXS"
    assert C._canonicalize_customer_code("BELLQXS", codes) == "DELLQXS"
    assert C._canonicalize_customer_code("DELLQS", codes) == "DELLQXS"


def test_confirming_create_absorbs_correction_and_snaps_code():
    # Regression: a non-yes/no reply at confirm must update fields (not loop), and
    # the mis-heard customer code must snap to the authorized one.
    cf = {
        "Customer Code": "DELLQS", "Product Reference": "BDQ", "Contact Name": "Rachit",
        "Contact Phone": "9650470567", "Customer City": "Round Rock",
        "Customer State": "TX", "Customer Postal Code": "78682",
    }
    out = C.converse({
        "stage": "confirming_create", "intent": "create_wo", "context": CTX,
        "create_fields": cf, "messages": [],
        "user_message": "the customer code is BELLQXS",
    })
    assert out["stage"] == "confirming_create"
    assert (out.get("create_fields") or {}).get("Customer Code") == "DELLQXS"
    assert (out.get("create_fields") or {}).get("Product Reference") == "BDQ"


def test_not_is_not_a_denial():
    # Regression: "no" was substring-matching inside "not".
    assert C._is_deny_utterance("product BDQ not BBQ") is False
    assert C._is_deny_utterance("notebook is broken") is False
    assert C._is_deny_utterance("no") is True
    assert C._is_deny_utterance("change the product") is True


def test_closest_product_code_snaps_mishear():
    products = [{"code": "BDQ", "description": "Dell Latitude"}, {"code": "XYZ"}]
    assert C._closest_product_code("BBQ", products) == "BDQ"
    assert C._closest_product_code("BDQ", products) == "BDQ"
    assert C._closest_product_code("ZZZZZ", [{"code": "BDQ"}]) is None


def _full_create_fields(product="BBQ"):
    return {
        "Customer Code": "DELLQXS", "Product Reference": product, "Contact Name": "Rahul",
        "Contact Phone": "9650470567", "Customer City": "Round Rock",
        "Customer State": "TX", "Customer Postal Code": "78682",
    }


def test_confirming_create_applies_product_correction_change_to():
    out = C.converse({
        "stage": "confirming_create", "intent": "create_wo", "context": CTX,
        "create_fields": _full_create_fields("BBQ"), "messages": [],
        "user_message": "change the product from BBQ to BDQ",
    })
    assert out["stage"] == "confirming_create"
    assert (out.get("create_fields") or {}).get("Product Reference") == "BDQ"


def test_confirming_create_applies_product_correction_not_phrasing():
    out = C.converse({
        "stage": "confirming_create", "intent": "create_wo", "context": CTX,
        "create_fields": _full_create_fields("BBQ"), "messages": [],
        "user_message": "product BDQ not BBQ",
    })
    assert (out.get("create_fields") or {}).get("Product Reference") == "BDQ"
    assert out["stage"] == "confirming_create"


def test_remark_sanitization_strips_apostrophes():
    # Regression: apostrophes truncated the stored remark ("It's" → "it's").
    assert "'" not in api._sanitize_remark("It's overheating")
    assert api._sanitize_remark("It's  overheating\n") == "Its overheating"


def test_remark_builders():
    st = {
        "ts_issue": "laptop won't power on", "ts_name": "Rachit",
        "ts_product_ref": "BDQ", "ts_resolved": False, "ts_executed": 2,
        "ts_troubleshoots": [
            {"title": "Power check", "steps": ["a", "b"]},
            {"title": "Display check", "steps": ["c"]},
        ],
    }
    r1 = E._build_ts_issue_remark(st)
    r2 = E._build_ts_analysis_remark(st, "Dell Latitude laptop", "BDQ")
    assert r1.startswith("User Comment") and "won't power on" in r1
    assert r2.startswith("AI Comment")
    assert "Power check" in r2 and "Display check" in r2
    assert "not resolved" in r2.lower()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
