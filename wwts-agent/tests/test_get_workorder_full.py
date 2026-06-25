"""Phase 1 — enriched get work order."""
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, "D:/real-time-voice/wwts-agent")
sys.path.insert(0, "D:/real-time-voice/server")

from wwts_agent import api
from wwts_agent.nodes.execute import execute


def _detail():
    return {
        "ordernum": "WU10090009",
        "custcode": "DELLQXS",
        "vstatus": "Open",
        "CSR": "TECH01",
        "laststop": "Dispatched",
    }


@patch("wwts_agent.api.GTService")
@patch("wwts_agent.api.get_workorder")
def test_get_workorder_full_includes_parts_and_labor(mock_get, mock_gts_cls):
    mock_get.return_value = {
        "success": True,
        "detail": _detail(),
        "remarks": [],
        "error": "",
    }
    gts = mock_gts_cls.return_value
    parts_resp = MagicMock(success=True, RC=0)
    parts_resp.results.return_value = [MagicMock(partno="ABC", partdesc="Power supply")]
    labor_resp = MagicMock(success=True, RC=0)
    labor_resp.results.return_value = [MagicMock(csr="TECH01", status="Active")]
    gts.GetCallParts.return_value = parts_resp
    gts.QueryLaborItems.return_value = labor_resp

    with patch("wwts_agent.api._to_dict", side_effect=lambda o: vars(o)):
        result = api.get_workorder_full(
            "USER",
            123,
            "WU10090009",
            customer_codes=[{"code": "DELLQXS"}],
        )

    assert result["success"] is True
    assert len(result["parts"]) == 1
    assert len(result["labor"]) == 1


@patch("wwts_agent.api.get_workorder")
def test_get_workorder_full_scope_check(mock_get):
    mock_get.return_value = {
        "success": True,
        "detail": {"ordernum": "WU1", "custcode": "OTHER"},
        "remarks": [],
        "error": "",
    }
    result = api.get_workorder_full(
        "USER", 1, "WU1", customer_codes=[{"code": "DELLQXS"}]
    )
    assert result["success"] is False
    assert "not in your authorized" in result["error"]


@patch("wwts_agent.api.get_workorder_full")
def test_do_get_scope_violation(mock_full):
    mock_full.return_value = {
        "success": False,
        "error": "Work order customer OTHER is not in your authorized customer list.",
        "parts": [],
        "labor": [],
    }
    state = execute(
        {
            "stage": "executing_get",
            "user_id": "USER",
            "wo_number": "WU1",
            "context": {"wwts_session": 1, "customer_codes": [{"code": "DELLQXS"}]},
        }
    )
    assert state["stage"] == "done"
    assert "not in your authorized" in state["speak"]


@patch("wwts_agent.api.get_workorder_full")
def test_do_get_parts_focus_speak(mock_full):
    mock_full.return_value = {
        "success": True,
        "detail": _detail(),
        "remarks": [],
        "parts": [{"partno": "P1"}, {"partno": "P2"}],
        "labor": [],
        "error": "",
    }
    state = execute(
        {
            "stage": "executing_get",
            "user_id": "USER",
            "wo_number": "WU10090009",
            "wo_get_focus": "parts",
            "context": {"wwts_session": 1, "customer_codes": [{"code": "DELLQXS"}]},
        }
    )
    assert "2 part line" in state["speak"]
