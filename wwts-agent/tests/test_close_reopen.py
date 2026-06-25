"""Phase 4b/4c close + reopen coverage."""
import os
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
        "authorized_functions": ["CloseCall", "ReopenWO"] if auth is None else auth,
    }


def _detail_open():
    return {"ordernum": "WU1001", "custcode": "DELLQXS", "vstatus": "Open", "closed": ""}


def _detail_closed():
    return {"ordernum": "WU1001", "custcode": "DELLQXS", "vstatus": "Closed", "closed": "01/01/26"}


@patch("wwts_agent.nodes.execute.api.close_workorder")
def test_close_flow_success_path(mock_close):
    mock_close.return_value = {"success": True, "RC": 0, "ResultMsg": "OK"}
    state = execute(
        {
            "stage": "executing_close",
            "user_id": "USER",
            "thread_id": "t-close-ok",
            "wo_number": "WU1001",
            "close_fields": {"Close Reason": "customer confirmed fix"},
            "wo_detail": _detail_open(),
            "context": _ctx(),
        }
    )
    assert state["stage"] == "done"
    assert "closed successfully" in state["final_answer"].lower()


@patch("wwts_agent.nodes.execute.api.reopen_workorder")
def test_reopen_flow_success_path(mock_reopen):
    mock_reopen.return_value = {"success": True, "RC": 0, "ResultMsg": "OK"}
    state = execute(
        {
            "stage": "executing_reopen",
            "user_id": "USER",
            "thread_id": "t-reopen-ok",
            "wo_number": "WU1001",
            "reopen_reason": "issue returned onsite",
            "wo_detail": _detail_closed(),
            "context": _ctx(),
        }
    )
    assert state["stage"] == "done"
    assert "reopened successfully" in state["final_answer"].lower()


@patch("wwts_agent.nodes.execute.api.close_workorder")
def test_auth_denied_for_close(mock_close):
    state = execute(
        {
            "stage": "executing_close",
            "user_id": "USER",
            "thread_id": "t-close-auth",
            "wo_number": "WU1001",
            "close_fields": {"Close Reason": "customer confirmed fix"},
            "context": _ctx(auth=[]),
        }
    )
    mock_close.assert_not_called()
    assert state["stage"] == "done"
    assert "not authorized" in state["speak"].lower()


@patch("wwts_agent.nodes.execute.api.reopen_workorder")
def test_auth_denied_for_reopen(mock_reopen):
    state = execute(
        {
            "stage": "executing_reopen",
            "user_id": "USER",
            "thread_id": "t-reopen-auth",
            "wo_number": "WU1001",
            "reopen_reason": "issue returned onsite",
            "context": _ctx(auth=[]),
        }
    )
    mock_reopen.assert_not_called()
    assert state["stage"] == "done"
    assert "not authorized" in state["speak"].lower()


@patch("wwts_agent.nodes.converse.api.preflight_close_workorder")
def test_preflight_blocks_already_closed(mock_pre):
    mock_pre.return_value = {
        "success": False,
        "detail": _detail_closed(),
        "error": "Work order WU1001 is already closed.",
        "already_closed": True,
    }
    state = converse(
        {
            "stage": "collecting_close_reason",
            "intent": "close_wo",
            "user_message": "reason: customer confirmed fix",
            "wo_number": "WU1001",
            "close_fields": {},
            "context": _ctx(),
            "messages": [],
        }
    )
    assert state["stage"] == "done"
    assert "already closed" in state["final_answer"].lower()


@patch("wwts_agent.nodes.converse.api.preflight_reopen_workorder")
def test_preflight_blocks_already_open(mock_pre):
    mock_pre.return_value = {
        "success": False,
        "detail": _detail_open(),
        "error": "Work order WU1001 is already open.",
        "already_open": True,
    }
    state = converse(
        {
            "stage": "collecting_reopen_reason",
            "intent": "reopen_wo",
            "user_message": "reason: issue returned onsite",
            "wo_number": "WU1001",
            "reopen_reason": "",
            "context": _ctx(),
            "messages": [],
        }
    )
    assert state["stage"] == "done"
    assert "already open" in state["final_answer"].lower()


@patch("wwts_agent.nodes.execute.api.close_workorder")
def test_customer_scope_rejection_on_close(mock_close):
    mock_close.return_value = {
        "success": False,
        "RC": -1,
        "error": "Work order customer OTHER is not in your authorized customer list.",
    }
    state = execute(
        {
            "stage": "executing_close",
            "user_id": "USER",
            "thread_id": "t-close-scope",
            "wo_number": "WU1001",
            "close_fields": {"Close Reason": "customer confirmed fix"},
            "context": _ctx(),
        }
    )
    assert state["stage"] == "done"
    assert "authorized customer list" in state["final_answer"]


@patch("wwts_agent.nodes.execute.api.reopen_workorder")
def test_customer_scope_rejection_on_reopen(mock_reopen):
    mock_reopen.return_value = {
        "success": False,
        "RC": -1,
        "error": "Work order customer OTHER is not in your authorized customer list.",
    }
    state = execute(
        {
            "stage": "executing_reopen",
            "user_id": "USER",
            "thread_id": "t-reopen-scope",
            "wo_number": "WU1001",
            "reopen_reason": "issue returned onsite",
            "context": _ctx(),
        }
    )
    assert state["stage"] == "done"
    assert "authorized customer list" in state["final_answer"]


def test_confirmation_stage_transitions_to_executing():
    close_state = converse(
        {
            "stage": "confirming_close",
            "intent": "close_wo",
            "user_message": "yes, close it",
            "wo_number": "WU1001",
            "close_fields": {"Close Reason": "customer confirmed fix"},
            "context": _ctx(),
            "messages": [],
        }
    )
    reopen_state = converse(
        {
            "stage": "confirming_reopen",
            "intent": "reopen_wo",
            "user_message": "yes, reopen it",
            "wo_number": "WU1001",
            "reopen_reason": "issue returned onsite",
            "context": _ctx(),
            "messages": [],
        }
    )
    assert close_state["stage"] == "executing_close"
    assert reopen_state["stage"] == "executing_reopen"


@patch("wwts_agent.nodes.execute.api.close_workorder")
@patch("wwts_agent.nodes.execute.api.reopen_workorder")
def test_rc_handling_for_mutation_failures(mock_reopen, mock_close):
    mock_close.return_value = {"success": False, "RC": 5, "ResultMsg": "Close blocked", "error": ""}
    mock_reopen.return_value = {"success": False, "RC": 7, "ResultMsg": "Reopen blocked", "error": ""}
    close_state = execute(
        {
            "stage": "executing_close",
            "user_id": "USER",
            "thread_id": "t-close-rc",
            "wo_number": "WU1001",
            "close_fields": {"Close Reason": "customer confirmed fix"},
            "context": _ctx(),
        }
    )
    reopen_state = execute(
        {
            "stage": "executing_reopen",
            "user_id": "USER",
            "thread_id": "t-reopen-rc",
            "wo_number": "WU1001",
            "reopen_reason": "issue returned onsite",
            "context": _ctx(),
        }
    )
    assert "failed to close" in close_state["final_answer"].lower()
    assert "failed to reopen" in reopen_state["final_answer"].lower()


@patch("wwts_agent.nodes.converse.api.preflight_close_workorder")
@patch("wwts_agent.nodes.converse.api.preflight_reopen_workorder")
@patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False)
def test_fallback_routing_reaches_close_and_reopen(mock_preflight_reopen, mock_preflight_close):
    mock_preflight_close.return_value = {"success": True, "detail": _detail_open(), "error": ""}
    mock_preflight_reopen.return_value = {"success": True, "detail": _detail_closed(), "error": ""}
    close_state = converse(
        {
            "stage": "intent",
            "intent": None,
            "user_message": "close work order WU1001 because customer confirmed fix",
            "context": _ctx(),
            "messages": [],
        }
    )
    reopen_state = converse(
        {
            "stage": "intent",
            "intent": None,
            "user_message": "reopen work order WU1001 because issue returned onsite",
            "context": _ctx(),
            "messages": [],
        }
    )
    assert close_state["intent"] == "close_wo"
    assert close_state["stage"] == "confirming_close"
    assert reopen_state["intent"] == "reopen_wo"
    assert reopen_state["stage"] == "confirming_reopen"


@patch("langchain_openai.ChatOpenAI")
@patch("wwts_agent.nodes.converse.api.preflight_close_workorder")
def test_llm_path_hardening_keeps_close_reachable(mock_preflight, mock_chat_cls):
    mock_preflight.return_value = {"success": True, "detail": _detail_open(), "error": ""}
    mock_chat = mock_chat_cls.return_value
    mock_chat.invoke.return_value.content = (
        '{"response":"How can I help?","speak":"How can I help?",'
        '"new_stage":"intent","extracted":{"intent":null,"wo_number":null}}'
    )
    state = converse(
        {
            "stage": "intent",
            "intent": None,
            "user_message": "close WO WU1001 because customer confirmed fix",
            "context": _ctx(),
            "messages": [],
        }
    )
    assert state["intent"] == "close_wo"
    assert state["stage"] == "confirming_close"
