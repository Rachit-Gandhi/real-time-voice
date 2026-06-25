"""Canonical WWTS correction propagation."""
import sys

sys.path.insert(0, "D:/real-time-voice/wwts-agent")
sys.path.insert(0, "D:/real-time-voice/server")

from wwts_agent.corrections import apply_user_corrections, hydrate_state, sync_legacy_fields
from wwts_agent.nodes.converse import (
    converse,
    _apply_create_corrections,
    _missing_create_fields,
    _extract_name,
    _name_said_by_caller,
)
from wwts_agent.nodes.converse import _extract_product_ref_correction
from wwts_agent.nodes.execute import _build_ts_analysis_remark, _build_ts_issue_remark


CUSTOMERS = [{"code": "DELLQXS", "name": "Dell QXS"}]


def test_product_correction_ignores_sentiment_words():
    # "you got my product wrong, my product is BDQ" → BDQ, never "WRONG".
    assert _extract_product_ref_correction("No you got my product wrong my product is BDQ") == "BDQ"
    assert _extract_product_ref_correction("No, the product is BDQ") == "BDQ"
    assert _extract_product_ref_correction("BDQ not BBQ") == "BDQ"
    # A street-address reply carries no product correction.
    assert _extract_product_ref_correction(
        "The street address for this site is 1 Delvey, Round Rock, Texas 78682."
    ) is None


def test_failed_troubleshoot_reply_does_not_correct_product_to_did():
    state = hydrate_state(
        {
            "stage": "ts_troubleshooting",
            "intent": "troubleshoot",
            "ts_name": "Rahul",
            "ts_product_ref": "BDQ",
            "context": {"customer_codes": CUSTOMERS},
        }
    )

    result, applied = apply_user_corrections(
        state,
        "No, I have already tried this troubleshoot and it did not help me out.",
        customer_codes=CUSTOMERS,
    )

    assert applied == []
    assert result["ts_product_ref"] == "BDQ"
    assert result["facts"]["product_ref"]["value"] == "BDQ"


def test_street_address_reply_does_not_clobber_known_product():
    state = {
        "stage": "confirming_create",
        "intent": "create_wo",
        "create_fields": {
            "Customer Code": "DELLQXS", "Product Reference": "BDQ",
            "Contact Name": "Rachit Gandhi", "Contact Phone": "9650470567",
            "Customer City": "Round Rock", "Customer State": "TX", "Customer Postal Code": "78682",
        },
        "context": {"customer_codes": CUSTOMERS},
        "messages": [],
        "user_message": "The street address for this site is 1 Delvey, Round Rock, Texas 78682.",
    }
    result = converse(state)
    assert result["create_fields"]["Product Reference"] == "BDQ"


def test_missing_fields_asks_for_address_not_site_id():
    """The create ask should request the address, never the Site ID up front."""
    missing = _missing_create_fields(
        {"Product Reference": "BDQ", "Contact Name": "Rachit", "Contact Phone": "9650470567"},
        has_customer_code=True,
    )
    assert any("City" in m for m in missing)
    assert all("Site ID" not in m for m in missing)


def test_filler_reply_not_accepted_as_name():
    """A non-name reply ("Thanks.") to the name prompt must NOT be accepted as a
    name — the agent should re-ask instead of greeting a hallucinated/filler name."""
    state = {
        "stage": "ts_collecting_name",
        "intent": "troubleshoot",
        "ts_name": None,
        "context": {"customer_codes": CUSTOMERS},
        "messages": [{"role": "assistant", "content": "may I have your name?"}],
        "user_message": "Thanks.",
    }
    result = converse(state)
    assert result["stage"] == "ts_collecting_name"
    assert "Nice to meet you" not in result["speak"]
    assert not (result.get("ts_name") or "")


def test_hinglish_name_patterns_extract_name():
    assert _extract_name("mera naam Rachit hai") == "Rachit"
    assert _extract_name("main Rachit hoon") == "Rachit"
    assert _extract_name("naam Rachit") == "Rachit"


def test_name_guard_trusts_transliteration_from_devanagari():
    # Romanised name extracted from Hindi/Devanagari input must be accepted...
    assert _name_said_by_caller("Rachit", [], "मेरा नाम रच्चत है") is True
    # ...but an invented name for an ASCII non-name reply must still be rejected.
    assert _name_said_by_caller("Alex Rivera", [], "Thanks.") is False


def test_hinglish_name_reply_accepted_in_flow():
    state = {
        "stage": "ts_collecting_name",
        "intent": "troubleshoot",
        "ts_name": None,
        "context": {"customer_codes": CUSTOMERS},
        "messages": [{"role": "assistant", "content": "may I have your name?"}],
        "user_message": "mera naam Rachit hai",
    }
    result = converse(state)
    assert (result.get("ts_name") or "") == "Rachit"


def test_product_ref_recovered_from_earlier_turn():
    """Voice VAD can split one breath into separate turns; a product reference
    given (with a cue) in an earlier turn must still be picked up rather than the
    agent re-asking for it."""
    state = {
        "stage": "ts_collecting_product",
        "intent": "troubleshoot",
        "ts_name": "Rachit",
        "ts_issue": "laptop overheating",
        "context": {"customer_codes": CUSTOMERS},
        "messages": [
            {"role": "assistant", "content": "Are you facing a technical difficulty?"},
            {"role": "user", "content": "my laptop is overheating, the product reference for this is BDQ"},
            {"role": "assistant", "content": "What's the product reference for the device?"},
        ],
        "user_message": "I already told you, it's the one I mentioned.",
    }
    result = converse(state)
    assert (result.get("ts_product_ref") or "") == "BDQ"
    assert result["stage"] == "ts_troubleshooting"


def test_known_product_not_clobbered_by_loose_reply():
    """A non-product reply that loosely yields a token must NOT overwrite a
    Product Reference the agent already captured (the BDQ→DID/ROUND bug)."""
    merged, changed = _apply_create_corrections(
        messages=[],
        user_message="DUMMY and Rachit Gandhi",  # short-pattern would yield product "DUMMY"
        create_fields={"Product Reference": "BDQ", "Customer Code": "DELLQXS"},
        customer_codes=CUSTOMERS,
    )
    assert merged["Product Reference"] == "BDQ"


def test_explicit_product_correction_still_overrides_known():
    """An explicit correction may still change a known Product Reference."""
    merged, _ = _apply_create_corrections(
        messages=[],
        user_message="the product is BDX",
        create_fields={"Product Reference": "BDQ", "Customer Code": "DELLQXS"},
        customer_codes=CUSTOMERS,
    )
    assert merged["Product Reference"] == "BDX"


def test_create_correction_updates_facts_and_legacy_fields():
    state = {
        "stage": "confirming_create",
        "intent": "create_wo",
        "create_fields": {
            "Customer Code": "DELLQXS",
            "Product Reference": "BBQ",
            "Contact Name": "Rachit Gandhi",
            "Contact Phone": "9650470567",
            "Customer City": "Round Rock",
            "Customer State": "TX",
            "Customer Postal Code": "78682",
        },
        "context": {"customer_codes": CUSTOMERS},
        "messages": [],
        "user_message": "BDQ not BBQ",
    }

    result = converse(state)

    assert result["stage"] == "confirming_create"
    assert result["create_fields"]["Product Reference"] == "BDQ"
    assert result["facts"]["product_ref"]["value"] == "BDQ"
    assert result["corrections"][-1]["field"] == "product_ref"


def test_search_correction_reroutes_with_corrected_filter_and_clears_stale_results():
    state = {
        "stage": "done",
        "intent": "search_wo",
        "search_filters": {"model": "bbq", "customer_code": "DELLQXS", "wo_status": "A"},
        "wo_list": [{"ordernum": "WU1"}],
        "context": {"customer_codes": CUSTOMERS},
        "messages": [],
        "user_message": "model should be BDQ not BBQ",
    }

    result = converse(state)

    assert result["stage"] == "executing_list"
    assert result["intent"] == "search_wo"
    assert result["search_filters"]["model"] == "bdq"
    assert result["wo_list"] is None
    assert result["facts"]["model"]["value"] == "bdq"


def test_work_order_correction_updates_target_and_invalidates_cached_detail():
    state = {
        "stage": "done",
        "intent": "get_wo",
        "wo_number": "WU1001",
        "wo_detail": {"ordernum": "WU1001"},
        "wo_parts": [{"partno": "OLD"}],
        "context": {"customer_codes": CUSTOMERS},
        "messages": [],
        "user_message": "not WU1001, it is WU1007",
    }

    result = converse(state)

    assert result["stage"] == "executing_get"
    assert result["wo_number"] == "WU1007"
    assert result["wo_detail"] is None
    assert result["wo_parts"] is None
    assert result["active_task"]["target_wo"] == "WU1007"


def test_troubleshoot_remarks_prefer_corrected_facts():
    state, applied = apply_user_corrections(
        hydrate_state(
            {
                "ts_name": "Rachit",
                "ts_issue": "no power",
                "ts_device": "laptop",
                "context": {"customer_codes": CUSTOMERS},
            }
        ),
        "actually the issue is overheating",
        customer_codes=CUSTOMERS,
    )
    state = sync_legacy_fields(state, changed_fields={c["field"] for c in applied})

    assert "overheating" in _build_ts_issue_remark(state)
    assert "Reported issue: overheating" in _build_ts_analysis_remark(state, "", "BDQ")
