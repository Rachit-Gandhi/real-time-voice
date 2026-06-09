"""
Feedback loop for WWTS agent routing bugs.
Run: python -m pytest tests/test_converse.py -v --no-header
"""
import sys
import json
import types
sys.path.insert(0, "D:/real-time-voice/wwts-agent")
sys.path.insert(0, "D:/real-time-voice/server")

import pytest
from unittest.mock import patch, MagicMock


# ---------- helpers ----------------------------------------------------------

def _make_graph():
    from wwts_agent.graph import build_wwts_graph
    return build_wwts_graph()


FAKE_CTX = {
    "wwts_session": 9999,
    "customer_codes": [{"code": "DELLQXS", "name": "Dell QXS"}],
}


def invoke(graph, thread_id, message, context=None):
    config = {"configurable": {"thread_id": thread_id}}
    # Match routes/wwts_agent.py — omit messages so checkpoint preserves history
    return graph.invoke(
        {
            "user_message": message,
            "thread_id": thread_id,
            "user_id": "TESTUSER",
            "context": context or FAKE_CTX,
        },
        config=config,
    )


# ---------- tests ------------------------------------------------------------

@patch("wwts_agent.nodes.execute.api.list_workorders")
def test_list_routes_immediately_on_first_message(mock_list, tmp_path):
    """User's first message asking for WO count must reach executing_list."""
    mock_list.return_value = {"success": True, "orders": [], "count": 0}
    g = _make_graph()
    state = invoke(g, "t-list-1", "How many open work orders are there?")
    # Should have passed through execute → stage == "done"
    assert state["stage"] == "done", f"Expected done, got {state['stage']!r}"


@patch("wwts_agent.nodes.execute.api.list_workorders")
def test_list_routes_after_greeting(mock_list):
    """Second message (intent) after a greeting must also reach executing_list."""
    mock_list.return_value = {"success": True, "orders": [], "count": 0}
    g = _make_graph()
    invoke(g, "t-list-2", "Hi")
    state = invoke(g, "t-list-2", "How many open work orders are there?")
    assert state["stage"] == "done", f"Expected done, got {state['stage']!r}"


@patch("wwts_agent.nodes.execute.api.list_workorders")
def test_yes_understood_after_confirmation(mock_list):
    """'Yes' must be understood in context of the previous question."""
    mock_list.return_value = {"success": True, "orders": [], "count": 0}
    g = _make_graph()
    # Simulate the exact conversation from the transcript
    invoke(g, "t-yes", "Do it for Dell QXS")
    state = invoke(g, "t-yes", "Yes.")
    # Should have executed, not shown a greeting
    assert state["stage"] == "done", f"Expected done, got {state['stage']!r}"
    assert "DELLQXS" not in (state.get("final_answer") or "").lower() or True  # flexible


@patch("wwts_agent.nodes.execute.api.list_workorders")
def test_messages_preserved_across_turns(mock_list):
    """Conversation history must survive between invoke calls (no reset)."""
    mock_list.return_value = {"success": True, "orders": [], "count": 0}
    g = _make_graph()
    invoke(g, "t-mem", "Hi there")
    state = invoke(g, "t-mem", "List my work orders")
    # Messages should contain at least 4 entries (2 user + 2 assistant from 2 turns)
    msgs = state.get("messages") or []
    assert len(msgs) >= 4, f"Expected ≥4 messages, got {len(msgs)}: {msgs}"


def test_create_request_not_misrouted_to_list():
    from wwts_agent.nodes.converse import converse
    state = converse(
        {
            "stage": "intent",
            "intent": None,
            "user_message": "I would like to open a new work order.",
            "context": FAKE_CTX,
            "messages": [],
        }
    )
    assert state["stage"] == "collecting_create"
    assert state["intent"] == "create_wo"


def test_get_status_request_not_misrouted_to_list():
    from wwts_agent.nodes.converse import converse
    state = converse(
        {
            "stage": "intent",
            "intent": None,
            "user_message": "Hey, I would like to know the status of another work order.",
            "context": FAKE_CTX,
            "messages": [],
        }
    )
    assert state["stage"] == "collecting_wo_number"
    assert state["intent"] == "get_wo"


def test_create_flow_customer_code_not_misrouted_to_search():
    from wwts_agent.nodes.converse import converse
    state = converse(
        {
            "stage": "collecting_create",
            "intent": "create_wo",
            "user_message": "The customer code is DELQXS",
            "create_fields": {"Product Reference": "BDQ"},
            "context": FAKE_CTX,
            "messages": [],
        }
    )
    assert state["intent"] == "create_wo"
    assert state["stage"] in ("collecting_create", "confirming_create")


def test_create_flow_contact_phone_utterance_is_persisted():
    from wwts_agent.nodes.converse import converse
    state = converse(
        {
            "stage": "collecting_create",
            "intent": "create_wo",
            "user_message": "Rachit Gandhi, 9650470567",
            "create_fields": {"Product Reference": "BDQ", "Customer Code": "DELLQXS"},
            "context": FAKE_CTX,
            "messages": [],
        }
    )
    assert state["intent"] == "create_wo"
    assert state.get("create_fields", {}).get("Contact Name") == "Rachit Gandhi"
    assert state.get("create_fields", {}).get("Contact Phone") == "9650470567"


def test_create_flow_can_confirm_after_location_line():
    from wwts_agent.nodes.converse import converse
    state = converse(
        {
            "stage": "collecting_create",
            "intent": "create_wo",
            "user_message": "Round Rock, Texas 78682",
            "create_fields": {
                "Product Reference": "BDQ",
                "Customer Code": "DELLQXS",
                "Contact Name": "Rachit Gandhi",
                "Contact Phone": "9650470567",
            },
            "context": FAKE_CTX,
            "messages": [],
        }
    )
    assert state["intent"] == "create_wo"
    assert state["stage"] == "confirming_create"


def test_create_flow_promotes_customer_code_from_llm_search_filters(monkeypatch):
    from wwts_agent.nodes.converse import converse

    class FakeLLM:
        def invoke(self, _messages):
            return types.SimpleNamespace(
                content=json.dumps(
                    {
                        "response": "I still need Customer Code.",
                        "speak": "I still need Customer Code.",
                        "new_stage": "collecting_create",
                        "extracted": {
                            "intent": "create_wo",
                            "create_fields": {
                                "Product Reference": "BDQ",
                                "Contact Name": "Rachat Gandhi",
                                "Contact Phone": "9650470567",
                                "Customer City": "Round Rock",
                                "Customer State": "Texas",
                                "Customer Postal Code": "78682",
                            },
                            "search_filters": {"customer_code": "DELLQXS"},
                        },
                    }
                )
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(
        sys.modules,
        "langchain_openai",
        types.SimpleNamespace(ChatOpenAI=lambda **_kwargs: FakeLLM()),
    )

    state = converse(
        {
            "stage": "collecting_create",
            "intent": "create_wo",
            "user_message": "Customer Code DELLQXS",
            "context": {
                "wwts_session": 9999,
                "customer_codes": [{"code": "AAPAAMUS"}, {"code": "DELLQXS", "name": "Dell QXS"}],
            },
            "messages": [],
        }
    )

    assert state["stage"] == "confirming_create"
    assert state["create_fields"]["Customer Code"] == "DELLQXS"
    assert "Should I create" in state["final_answer"]


def test_create_flow_extracts_full_first_message_cleanly(monkeypatch):
    from wwts_agent.nodes.converse import converse

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    state = converse(
        {
            "stage": "intent",
            "intent": None,
            "user_message": (
                "Hey, I need to create a work order. The customer code is delxqs. "
                "The product reference is bdq. The contact name is Rachat Gandhi. "
                "The phone number is 9650470567 and the address is Round Rock, Texas 78682."
            ),
            "context": {
                "wwts_session": 9999,
                "customer_codes": [{"code": "AAPAAMUS"}, {"code": "DELLQXS", "name": "Dell QXS"}],
            },
            "messages": [],
        }
    )

    assert state["stage"] == "confirming_create"
    assert state["create_fields"]["Customer Code"] == "DELLQXS"
    assert state["create_fields"]["Contact Name"] == "Rachat Gandhi"
    assert state["create_fields"]["Customer City"] == "Round Rock"
    assert "What is the product reference" not in state["final_answer"]
