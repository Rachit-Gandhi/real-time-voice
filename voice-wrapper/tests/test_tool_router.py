"""Tests for tool router."""
import pytest


def test_dispatch_run_agent_with_mock_handler():
    """router.dispatch('run_agent', args) returns dict with answer and speak keys."""
    from apps.api.realtime.tool_router import ToolRouter

    def mock_run_agent(agent_id, user_message, session_id):
        return {"answer": "mock answer", "speak": "mock speak"}

    router = ToolRouter(agent_invoke_fn=mock_run_agent)
    result = router.dispatch(
        tool_name="run_agent",
        args={
            "agent_id": "agent_one",
            "user_message": "What is the refund policy?",
            "session_id": "s1",
        },
    )
    assert "answer" in result
    assert "speak" in result
    assert isinstance(result["answer"], str)
    assert isinstance(result["speak"], str)


def test_dispatch_unknown_tool_raises():
    """router.dispatch with unknown tool_name raises ValueError."""
    from apps.api.realtime.tool_router import ToolRouter

    def mock_run_agent(agent_id, user_message, session_id):
        return {"answer": "x", "speak": "x"}

    router = ToolRouter(agent_invoke_fn=mock_run_agent)
    with pytest.raises(ValueError):
        router.dispatch(tool_name="unknown_tool", args={})
