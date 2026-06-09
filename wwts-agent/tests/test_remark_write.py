"""Phase 5 — optional guarded remark write coverage."""
import sys
from unittest.mock import patch

sys.path.insert(0, "D:/real-time-voice/wwts-agent")
sys.path.insert(0, "D:/real-time-voice/server")

from wwts_agent.nodes.converse import converse
from wwts_agent.nodes.execute import execute


def _ctx(*, auth=None):
    return {
        "wwts_session": 9999,
        "customer_codes": [{"code": "DELLQXS", "name": "Dell"}],
        "authorized_functions": ["InsertCallRemark"] if auth is None else auth,
    }


def _detail_open():
    return {"ordernum": "WU1001", "custcode": "DELLQXS", "vstatus": "Open", "closed": ""}


@patch("wwts_agent.nodes.converse.api.get_workorder_full")
def test_routing_to_remark_intent(mock_get):
    mock_get.return_value = {"success": True, "detail": _detail_open(), "error": "", "remarks": []}
    state = converse(
        {
            "stage": "intent",
            "intent": None,
            "user_message": "add a remark to work order WU1001 remark: customer requested callback",
            "context": _ctx(),
            "messages": [],
            "user_id": "USER",
        }
    )
    assert state["intent"] == "add_wo_remark"
    assert state["stage"] == "confirming_remark"


@patch("wwts_agent.nodes.converse.api.get_workorder_full")
def test_confirmation_stage_flow(mock_get):
    mock_get.return_value = {"success": True, "detail": _detail_open(), "error": "", "remarks": []}
    first = converse(
        {
            "stage": "intent",
            "intent": None,
            "user_message": "add note on WO WU1001 note: customer requested callback",
            "context": _ctx(),
            "messages": [],
            "user_id": "USER",
        }
    )
    second = converse(
        {
            **first,
            "stage": "confirming_remark",
            "user_message": "yes, do it",
        }
    )
    assert second["stage"] == "executing_remark"


@patch("wwts_agent.nodes.execute.api.add_workorder_remark")
def test_auth_denied(mock_add):
    state = execute(
        {
            "stage": "executing_remark",
            "user_id": "USER",
            "thread_id": "t-remark-auth",
            "wo_number": "WU1001",
            "remark_text": "customer requested callback",
            "context": _ctx(auth=[]),
        }
    )
    mock_add.assert_not_called()
    assert state["stage"] == "done"
    assert "not authorized" in state["speak"].lower()


@patch("wwts_agent.nodes.execute.api.add_workorder_remark")
def test_scope_denied(mock_add):
    mock_add.return_value = {
        "success": False,
        "RC": -1,
        "error": "Work order customer OTHER is not in your authorized customer list.",
        "ResultMsg": "",
    }
    state = execute(
        {
            "stage": "executing_remark",
            "user_id": "USER",
            "thread_id": "t-remark-scope",
            "wo_number": "WU1001",
            "remark_text": "customer requested callback",
            "context": _ctx(),
        }
    )
    assert state["stage"] == "done"
    assert "authorized customer list" in state["final_answer"]


@patch("wwts_agent.nodes.execute.api.add_workorder_remark")
def test_successful_remark_write(mock_add):
    mock_add.return_value = {"success": True, "RC": 0, "ResultMsg": "OK", "OrderNum": "WU1001"}
    state = execute(
        {
            "stage": "executing_remark",
            "user_id": "USER",
            "thread_id": "t-remark-ok",
            "wo_number": "WU1001",
            "remark_text": "customer requested callback",
            "context": _ctx(),
        }
    )
    assert state["stage"] == "done"
    assert "remark added" in state["final_answer"].lower()


@patch("wwts_agent.nodes.execute.api.add_workorder_remark")
def test_mutation_failure_rc_path(mock_add):
    mock_add.return_value = {"success": False, "RC": 9, "ResultMsg": "Remark blocked", "error": ""}
    state = execute(
        {
            "stage": "executing_remark",
            "user_id": "USER",
            "thread_id": "t-remark-rc",
            "wo_number": "WU1001",
            "remark_text": "customer requested callback",
            "context": _ctx(),
        }
    )
    assert state["stage"] == "done"
    assert "failed to add remark" in state["final_answer"].lower()
