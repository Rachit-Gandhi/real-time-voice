"""Phase 2 — focused read intents."""
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "D:/real-time-voice/wwts-agent")
sys.path.insert(0, "D:/real-time-voice/server")

from wwts_agent import api
from wwts_agent.nodes.converse import (
    _detect_focused_read_intent,
    _extract_part_line_number,
    _route_focused_read,
    converse,
)
from wwts_agent.nodes.execute import execute

FAKE_CTX = {
    "wwts_session": 9999,
    "customer_codes": [{"code": "DELLQXS", "name": "Dell QXS"}],
    "authorized_functions": ["RequestForOpen"],
}

_DETAIL = {"ordernum": "WU10090009", "custcode": "DELLQXS", "CSR": "TECH01", "siteID": "SITE1"}


def test_detect_focused_read_intents():
    assert _detect_focused_read_intent("what parts are on WO WU1") == "get_wo_parts"
    assert _detect_focused_read_intent("show part line 3") == "get_wo_part_line"
    assert _detect_focused_read_intent("labor activities on this job") == "get_wo_labor_activities"
    assert _detect_focused_read_intent("site address for this wo") == "get_site"


def test_extract_part_line_number():
    assert _extract_part_line_number("part line 3 please") == 3
    assert _extract_part_line_number("line #12") == 12


def test_route_focused_read_requires_wo_number():
    stage, wo, line = _route_focused_read(
        "get_wo_parts", wo_number=None, wo_part_line=None, user_message="parts", stage="intent"
    )
    assert stage == "collecting_wo_number"
    assert wo is None


def test_route_part_line_needs_line():
    stage, wo, line = _route_focused_read(
        "get_wo_part_line",
        wo_number="WU1",
        wo_part_line=None,
        user_message="part detail",
        stage="intent",
    )
    assert stage == "collecting_wo_part_line"
    assert wo == "WU1"


@patch("wwts_agent.api.get_workorder")
def test_get_workorder_parts_scope_failure(mock_get):
    mock_get.return_value = {
        "success": True,
        "detail": {"custcode": "OTHER", "ordernum": "WU1"},
        "remarks": [],
        "error": "",
    }
    result = api.get_workorder_parts("U", 1, "WU1", [{"code": "DELLQXS"}])
    assert result["success"] is False
    assert "not in your authorized" in result["error"]


@patch("wwts_agent.api._wo_preflight_scope")
@patch("wwts_agent.api.GTService")
def test_get_workorder_parts_success(mock_gts_cls, mock_pre):
    mock_pre.return_value = {"success": True, "detail": _DETAIL, "error": ""}
    parts_resp = MagicMock(success=True, RC=0)
    parts_resp.results.return_value = [MagicMock(partno="P1")]
    mock_gts_cls.return_value.GetCallParts.return_value = parts_resp
    with patch("wwts_agent.api._to_dict", side_effect=lambda o: vars(o)):
        result = api.get_workorder_parts("U", 1, "WU10090009", [{"code": "DELLQXS"}])
    assert result["success"] is True
    assert len(result["parts"]) == 1


@patch("wwts_agent.api._wo_preflight_scope")
@patch("portals.wwits.apis.rest_services.requests.get")
def test_get_workorder_parts_accepts_partial_part_payload(mock_get, mock_pre):
    mock_pre.return_value = {"success": True, "detail": _DETAIL, "error": ""}
    mock_get.return_value.json.return_value = {
        "Parms": {
            "UserID": "U",
            "Env": "QA",
            "Version": "1",
            "Source": "WMP",
            "Session": 1,
            "OrderNum": "WU10090009",
            "Mode": "",
            "RC": 0,
            "ResultMsg": "",
        },
        "WO": [{"LineNum": 1, "PartNum": "P1"}],
    }

    result = api.get_workorder_parts("U", 1, "WU10090009", [{"code": "DELLQXS"}])

    assert result["success"] is True
    assert result["parts"] == [{"linenum": 1, "partnum": "P1"}]


@patch("wwts_agent.api.get_workorder_parts")
def test_execute_get_parts(mock_parts):
    mock_parts.return_value = {
        "success": True,
        "parts": [{"partno": "ABC", "partstatus": "Shipped"}],
        "detail": _DETAIL,
        "error": "",
    }
    state = execute(
        {
            "stage": "executing_get_parts",
            "user_id": "U",
            "wo_number": "WU10090009",
            "context": FAKE_CTX,
        }
    )
    assert state["stage"] == "done"
    assert "1 part line" in state["speak"]


@patch("wwts_agent.api.get_workorder_parts")
def test_execute_get_parts_formats_vendor_part_keys(mock_parts):
    mock_parts.return_value = {
        "success": True,
        "parts": [{"linenum": 1, "partnum": "P1", "descr": "Power supply", "linestatus": "Shipped"}],
        "detail": _DETAIL,
        "error": "",
    }
    state = execute(
        {
            "stage": "executing_get_parts",
            "user_id": "U",
            "wo_number": "WU10090009",
            "context": FAKE_CTX,
        }
    )
    assert "P1" in state["final_answer"]
    assert "Power supply" in state["final_answer"]
    assert "Shipped" in state["final_answer"]


@patch("wwts_agent.api.get_workorder_site")
def test_execute_get_site_minimal_speak(mock_site):
    mock_site.return_value = {
        "success": True,
        "site": {"City": "Round Rock", "State": "TX", "Zip": "78682", "SiteID": "SITE1"},
        "detail": _DETAIL,
        "error": "",
    }
    state = execute(
        {
            "stage": "executing_get_site",
            "user_id": "U",
            "wo_number": "WU10090009",
            "user_message": "site for this wo",
            "context": FAKE_CTX,
        }
    )
    assert state["stage"] == "done"
    assert "Round Rock" in state["speak"]
    assert "Street" not in state["speak"]


@patch("wwts_agent.api.get_workorder_site")
def test_execute_get_site_includes_street_when_asked(mock_site):
    mock_site.return_value = {
        "success": True,
        "site": {
            "City": "Round Rock",
            "State": "TX",
            "Zip": "78682",
            "SiteID": "SITE1",
            "StreetAddress": "123 Main St",
        },
        "detail": _DETAIL,
        "error": "",
    }
    state = execute(
        {
            "stage": "executing_get_site",
            "user_id": "U",
            "wo_number": "WU10090009",
            "user_message": "what is the street address",
            "context": FAKE_CTX,
        }
    )
    assert "123 Main St" in state["final_answer"]


def test_confirming_part_line_routes_to_execute():
    state = converse(
        {
            "stage": "collecting_wo_part_line",
            "intent": "get_wo_part_line",
            "wo_number": "WU10090009",
            "user_message": "line 2",
            "context": FAKE_CTX,
            "messages": [],
        }
    )
    assert state["stage"] == "executing_get_part_line"
    assert state["wo_part_line"] == 2
