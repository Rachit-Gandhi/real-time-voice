"""Tests for voice session API endpoints."""
from fastapi.testclient import TestClient


def test_create_voice_session():
    """POST /voice/session returns session_id, agent_id, and active status."""
    from apps.api.main import app

    client = TestClient(app)
    response = client.post(
        "/voice/session",
        json={"agent_id": "agent_one", "user_id": "user_123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["session_id"], str) and data["session_id"] != ""
    assert data["agent_id"] == "agent_one"
    assert data["status"] == "active"


def test_end_voice_session():
    """POST /voice/session/{session_id}/end returns session_id and ended status."""
    from apps.api.main import app

    client = TestClient(app)
    # First create a session to get a valid session_id
    create_resp = client.post(
        "/voice/session",
        json={"agent_id": "agent_one", "user_id": "user_123"},
    )
    session_id = create_resp.json()["session_id"]

    # Now end it
    end_resp = client.post(f"/voice/session/{session_id}/end")
    assert end_resp.status_code == 200
    data = end_resp.json()
    assert data["session_id"] == session_id
    assert data["status"] == "ended"
