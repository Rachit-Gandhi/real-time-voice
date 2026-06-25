"""Phase 4a — create confirmation, auth gate, audit."""
import logging
import sys
from unittest.mock import patch

sys.path.insert(0, "D:/real-time-voice/wwts-agent")
sys.path.insert(0, "D:/real-time-voice/server")

from wwts_agent import api
from wwts_agent.nodes.converse import converse, _build_create_summary, _missing_create_fields
from wwts_agent.nodes.execute import execute


def _ctx(**extra):
    base = {
        "wwts_session": 9999,
        "customer_codes": [{"code": "DELLQXS", "name": "Dell"}],
        "authorized_functions": ["RequestForOpen"],
    }
    base.update(extra)
    return base


def _complete_fields():
    return {
        "Customer Code": "DELLQXS",
        "Product Reference": "BDQ",
        "Contact Name": "Rachit Gandhi",
        "Contact Phone": "9650470567",
        "Customer City": "Round Rock",
        "Customer State": "TX",
        "Customer Postal Code": "78682",
    }


def test_missing_fields_blocks_confirming_stage():
    fields = {"Customer Code": "DELLQXS", "Product Reference": "BDQ"}
    assert _missing_create_fields(fields, has_customer_code=True) != []


def test_complete_fields_ready_for_confirm():
    fields = _complete_fields()
    assert _missing_create_fields(fields, has_customer_code=True) == []
    assert "Should I create" in _build_create_summary(fields)


def test_confirming_yes_routes_to_executing_create():
    state = converse(
        {
            "stage": "confirming_create",
            "intent": "create_wo",
            "user_message": "yes, go ahead",
            "create_fields": _complete_fields(),
            "context": _ctx(),
            "messages": [],
        }
    )
    assert state["stage"] == "executing_create"


@patch("wwts_agent.nodes.execute.api.create_workorder")
def test_execute_denied_without_create_authorization(mock_create):
    state = execute(
        {
            "stage": "executing_create",
            "user_id": "USER",
            "thread_id": "t1",
            "create_fields": _complete_fields(),
            "context": _ctx(authorized_functions=[]),
        }
    )
    mock_create.assert_not_called()
    assert state["stage"] == "done"
    assert "not authorized" in state["speak"].lower()


@patch("wwts_agent.nodes.execute.api.create_workorder")
def test_execute_create_after_confirm_logs_audit(mock_create, caplog):
    mock_create.return_value = {"success": True, "RC": 0, "OrderNum": "WU999", "ResultMsg": "OK"}
    fields = _complete_fields()
    with caplog.at_level(logging.INFO, logger="wwts_agent.audit"):
        state = execute(
            {
                "stage": "executing_create",
                "user_id": "USER",
                "thread_id": "t-confirm",
                "create_fields": fields,
                "context": _ctx(),
            }
        )
    assert state["stage"] == "done"
    assert state["created_wo_number"] == "WU999"
    audit_text = " ".join(r.message for r in caplog.records)
    assert "create_wo_attempt" in audit_text
    assert "create_wo_result" in audit_text


@patch("wwts_agent.nodes.execute.api.create_workorder")
def test_idempotency_blocks_duplicate_submit(mock_create):
    fields = _complete_fields()
    fp = api.create_fields_fingerprint(fields)
    state = execute(
        {
            "stage": "executing_create",
            "user_id": "USER",
            "thread_id": "t-dup",
            "create_fields": fields,
            "created_wo_number": "WU111",
            "create_fields_fingerprint": fp,
            "context": _ctx(),
        }
    )
    mock_create.assert_not_called()
    assert "already created" in state["speak"].lower()


def test_is_authorized_for_create_matches_request_for_open():
    assert api.is_authorized_for_create(["RequestForOpen"]) is True
    assert api.is_authorized_for_create(["DashBatchCallOpen"]) is True
    assert api.is_authorized_for_create(["menuBatchOpen"]) is True
    assert api.is_authorized_for_create(["DashCallOpenDTTM"]) is False
    assert api.is_authorized_for_create([]) is False
