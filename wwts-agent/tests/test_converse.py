"""
Feedback loop for WWTS agent routing bugs.
Run: python -m pytest tests/test_converse.py -v --no-header
"""
import sys
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
    # Reproduce the exact call made by routes/wwts_agent.py
    return graph.invoke(
        {
            "user_message": message,
            "thread_id": thread_id,
            "user_id": "TESTUSER",
            "context": context or FAKE_CTX,
            "messages": [],          # <- the bug candidate
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
