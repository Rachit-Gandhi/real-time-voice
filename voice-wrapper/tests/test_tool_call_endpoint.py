"""Tests for the tool-call endpoint."""
from fastapi.testclient import TestClient


def test_tool_call_endpoint_run_agent():
    """POST /voice/session/{id}/tool-call with run_agent returns {answer, speak}."""
    from apps.api.main import app

    # Override agent_invoke_fn with a mock on app state
    def mock_invoke(agent_id, user_message, session_id):
        return {"answer": "mocked answer", "speak": "mocked speak"}

    app.state.agent_invoke_fn = mock_invoke

    client = TestClient(app)

    # Create a session first
    create_resp = client.post(
        "/voice/session",
        json={"agent_id": "agent_one", "user_id": "user_123"},
    )
    session_id = create_resp.json()["session_id"]

    # Call the tool-call endpoint
    response = client.post(
        f"/voice/session/{session_id}/tool-call",
        json={
            "tool_name": "run_agent",
            "args": {
                "agent_id": "agent_one",
                "user_message": "What is the return policy?",
                "session_id": session_id,
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "speak" in data
    assert isinstance(data["answer"], str)
    assert isinstance(data["speak"], str)
