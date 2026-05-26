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


def test_get_session_status():
    """GET /voice/session/{session_id}/status returns full session object."""
    from apps.api.main import app

    client = TestClient(app)
    create_resp = client.post(
        "/voice/session",
        json={"agent_id": "agent_one", "user_id": "user_456"},
    )
    session_id = create_resp.json()["session_id"]

    status_resp = client.get(f"/voice/session/{session_id}/status")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["session_id"] == session_id
    assert data["agent_id"] == "agent_one"
    assert data["user_id"] == "user_456"
    assert data["status"] == "active"
    assert "started_at" in data


def test_get_session_status_not_found():
    """GET /voice/session/{session_id}/status returns 404 for unknown session."""
    from apps.api.main import app

    client = TestClient(app)
    resp = client.get("/voice/session/does-not-exist/status")
    assert resp.status_code == 404
