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
