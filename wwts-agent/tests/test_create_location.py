import sys
from unittest.mock import patch

sys.path.insert(0, "D:/real-time-voice/wwts-agent")
sys.path.insert(0, "D:/real-time-voice/server")

from wwts_agent.nodes.converse import _missing_create_fields, _normalize_create_fields
from wwts_agent.nodes.execute import execute


def _base_create_fields(**overrides):
    fields = {
        "Customer Code": "DELLQXS",
        "Product Reference": "BDQ",
        "Contact Name": "Rachit Gandhi",
        "Contact Phone": "965-047-0567",
    }
    fields.update(overrides)
    return fields


def test_no_site_location_requires_state():
    missing = _missing_create_fields(
        _base_create_fields(
            **{
                "Customer City": "Round Rock",
                "Customer Postal Code": "78682",
            }
        ),
        has_customer_code=True,
    )

    assert missing == ["Site ID or (Customer City + Customer State + Postal Code)"]


def test_city_state_in_city_field_satisfies_location():
    fields = _normalize_create_fields(
        _base_create_fields(
            **{
                "Customer City": "Round Rock, Texas",
                "Customer Postal Code": "78682",
            }
        )
    )

    assert fields["Customer City"] == "Round Rock"
    assert fields["Customer State"] == "Texas"
    assert _missing_create_fields(fields, has_customer_code=True) == []


@patch("wwts_agent.nodes.execute.api.create_workorder")
def test_execute_asks_for_state_before_create_api_call(mock_create):
    state = execute(
        {
            "stage": "executing_create",
            "user_id": "TESTUSER",
            "context": {"wwts_session": 9999},
            "create_fields": _base_create_fields(
                **{
                    "Customer City": "Round Rock",
                    "Customer Postal Code": "78682",
                }
            ),
        }
    )

    mock_create.assert_not_called()
    assert state["stage"] == "collecting_create"
    assert "state" in state["final_answer"].lower()


@patch("wwts_agent.nodes.execute.api.create_workorder")
def test_execute_normalizes_spoken_city_state_before_create_api_call(mock_create):
    mock_create.return_value = {"success": True, "OrderNum": "WO123"}

    state = execute(
        {
            "stage": "executing_create",
            "user_id": "TESTUSER",
            "context": {"wwts_session": 9999},
            "create_fields": _base_create_fields(
                **{
                    "Customer City": "Round Rock, Texas",
                    "Customer Postal Code": "78682",
                }
            ),
        }
    )

    submitted_fields = mock_create.call_args.args[2]
    assert submitted_fields["Customer City"] == "Round Rock"
    assert submitted_fields["Customer State"] == "TX"
    assert state["stage"] == "done"
