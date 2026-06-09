"""Canonical WWTS correction propagation."""
import sys

sys.path.insert(0, "D:/real-time-voice/wwts-agent")
sys.path.insert(0, "D:/real-time-voice/server")

from wwts_agent.corrections import apply_user_corrections, hydrate_state, sync_legacy_fields
from wwts_agent.nodes.converse import converse
from wwts_agent.nodes.execute import _build_ts_analysis_remark, _build_ts_issue_remark


CUSTOMERS = [{"code": "DELLQXS", "name": "Dell QXS"}]


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
