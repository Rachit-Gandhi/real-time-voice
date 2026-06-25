"""Phase 3 — search work orders via QueryCustomerOrders filters."""
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "D:/real-time-voice/wwts-agent")
sys.path.insert(0, "D:/real-time-voice/server")

from wwts_agent import api
from wwts_agent.nodes.converse import (
    _detect_days_back,
    _detect_wo_status,
    _detect_focused_read_intent,
    _extract_search_filters_from_text,
    _is_search_request,
    _missing_search_criteria,
    _detect_lifecycle_intent,
    _match_customer_from_utterance,
    converse,
)
from wwts_agent.nodes.execute import execute

FAKE_CTX = {
    "wwts_session": 9999,
    "customer_codes": [{"code": "DELLQXS", "name": "Dell QXS"}],
}


def test_is_search_vs_list():
    assert _is_search_request("find orders for customer call 12345") is True
    assert _is_search_request("how many open work orders do I have") is False
    assert _is_search_request("list the last 5 customer orders for customer id dell xqs") is True


def test_extract_search_filters_from_text():
    found = _extract_search_filters_from_text(
        "Find orders for customer call number ABC123 with model XPS15"
    )
    assert found.get("cust_call") == "abc123"
    assert found.get("model") == "xps15"


def test_extract_last_n_result_limit():
    found = _extract_search_filters_from_text(
        "list only the last five closed orders for customer id dell xqs"
    )
    assert found.get("result_limit") == 5
    found_numeric = _extract_search_filters_from_text(
        "list only the last 5 closed orders for customer id dell xqs"
    )
    assert found_numeric.get("result_limit") == 5


def test_extract_customer_code_from_customer_id_phrase():
    found = _extract_search_filters_from_text(
        "Show work orders for customer ID DellXQS"
    )
    assert found.get("customer_code") == "dellxqs"


def test_detect_not_open_status_as_closed():
    assert _detect_wo_status("show not open work orders") == "C"


def test_detect_beyond_last_days_expands_window():
    assert _detect_days_back("search beyond last 90 days") >= 180


def test_detect_month_year_window():
    assert _detect_days_back("Search for January month 2096") is not None


def test_has_search_criteria_accepts_customer_code_only():
    assert api._has_search_criteria({"customer_code": "DELLQXS"}, multi_codes=True) is True


def test_collecting_search_matches_spoken_customer_name_from_context():
    state = converse(
        {
            "stage": "collecting_search_criteria",
            "intent": "search_wo",
            "user_message": "Customer Code is Dell XQS",
            "search_filters": {"wo_status": "C"},
            "context": {
                "wwts_session": 9999,
                "customer_codes": [{"code": "DELLQXS", "name": "Dell XQS"}],
            },
            "messages": [],
        }
    )
    assert state["stage"] == "executing_list"
    assert state["search_filters"].get("customer_code") == "DELLQXS"
    assert state["search_filters"].get("wo_status") == "C"


def test_customer_match_tolerates_stt_swaps():
    code = _match_customer_from_utterance(
        "customer id dell xps",
        [{"code": "DELLQXS", "name": "Dell QXS"}],
    )
    assert code == "DELLQXS"


def test_closed_orders_not_routed_as_close_lifecycle():
    assert _detect_lifecycle_intent("find all closed work orders for this customer") is None


def test_missing_search_requires_criterion():
    assert _missing_search_criteria({}, multi_codes=False) != []


def test_search_not_confused_with_part_line_intent():
    assert _detect_focused_read_intent("show part line 3") == "get_wo_part_line"


@patch("wwts_agent.api.get_workorder")
@patch("wwts_agent.api.GTService")
def test_search_workorders_passes_portal_filters(mock_gts_cls, mock_get):
    mock_get.return_value = {
        "success": True,
        "detail": {"custcode": "DELLQXS", "ordernum": "WU1"},
        "remarks": [],
        "error": "",
    }
    orders_resp = MagicMock(success=True, RC=0)
    orders_resp.results.return_value = [MagicMock(ordernum="WU1", custcall="ABC123")]
    mock_gts_cls.return_value.QueryCustomerOrders.return_value = orders_resp

    with patch("wwts_agent.api._to_dict", side_effect=lambda o: vars(o)):
        result = api.search_workorders(
            "USER",
            1,
            [{"code": "DELLQXS"}],
            {"cust_call": "ABC123", "wo_status": "A"},
        )

    assert result["success"] is True
    assert result["count"] == 1
    call_kwargs = mock_gts_cls.return_value.QueryCustomerOrders.call_args
    assert call_kwargs.kwargs.get("CustCall") == "ABC123"


@patch("wwts_agent.api._query_orders_for_code")
def test_search_rejects_out_of_scope_customer(mock_query):
    result = api.search_workorders(
        "USER",
        1,
        [{"code": "DELLQXS"}],
        {"customer_code": "OTHER", "cust_call": "X"},
    )
    assert result["success"] is False
    assert "not in your authorized" in result["error"]
    mock_query.assert_not_called()


@patch("wwts_agent.nodes.execute.api.search_workorders")
def test_execute_search_wo(mock_search):
    mock_search.return_value = {
        "success": True,
        "orders": [{"ordernum": "WU99", "city": "Austin", "model": "X", "laststop": "Open"}],
    }
    state = execute(
        {
            "stage": "executing_list",
            "intent": "search_wo",
            "user_id": "USER",
            "search_filters": {"cust_call": "REF1", "wo_status": "A"},
            "context": FAKE_CTX,
        }
    )
    assert state["stage"] == "done"
    assert "matching" in state["speak"].lower()
    mock_search.assert_called_once()


@patch("wwts_agent.nodes.execute.api.search_workorders")
def test_execute_search_wo_respects_result_limit(mock_search):
    mock_search.return_value = {
        "success": True,
        "orders": [
            {"ordernum": "WU1", "city": "Austin", "model": "X", "laststop": "Closed"},
            {"ordernum": "WU2", "city": "Austin", "model": "X", "laststop": "Closed"},
            {"ordernum": "WU3", "city": "Austin", "model": "X", "laststop": "Closed"},
        ],
    }
    state = execute(
        {
            "stage": "executing_list",
            "intent": "search_wo",
            "user_id": "USER",
            "search_filters": {"customer_code": "DELLQXS", "wo_status": "C", "result_limit": 2},
            "context": FAKE_CTX,
        }
    )
    assert state["stage"] == "done"
    assert len(state["wo_list"]) == 2
    assert state["result_limit"] == 2


@patch("wwts_agent.nodes.execute.api.search_workorders")
def test_execute_search_wo_empty_uses_filter_message(mock_search):
    mock_search.return_value = {"success": True, "orders": []}
    state = execute(
        {
            "stage": "executing_list",
            "intent": "search_wo",
            "user_id": "USER",
            "search_filters": {"cust_call": "REF1", "wo_status": "C", "days_back": 180},
            "context": FAKE_CTX,
        }
    )
    assert state["stage"] == "done"
    assert "requested filters" in state["final_answer"].lower()


def test_collecting_search_routes_when_complete():
    state = converse(
        {
            "stage": "collecting_search_criteria",
            "intent": "search_wo",
            "user_message": "customer call number 5551212",
            "search_filters": {},
            "context": FAKE_CTX,
            "messages": [],
        }
    )
    assert state["stage"] == "executing_list"
    assert state["intent"] == "search_wo"
    assert state["search_filters"].get("cust_call") == "5551212"
