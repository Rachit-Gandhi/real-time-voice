"""Tests for voice session API endpoints."""
from fastapi.testclient import TestClient
import pytest


class FakeRealtimeClient:
    async def create_client_secret(self, *, instructions: str, tools=None):
        return {
            "expires_at": 123,
            "value": "ek_test",
            "session": {
                "type": "realtime",
            },
        }


@pytest.fixture(autouse=True)
def fake_app_state():
    from apps.api.agents.registry import AgentRegistry
    from apps.api.main import app
    from apps.api.realtime.session_manager import SessionManager

    session_manager = SessionManager(
        realtime_client=FakeRealtimeClient(),
        registry=AgentRegistry(),
    )
    app.state.session_manager = session_manager
    app.state.sessions = session_manager._sessions

    async def fake_agent_invoke_fn(agent_id, user_message, session_id, user_id=None, context=None):
        return {
            "answer": f"answer: {user_message}",
            "speak": f"speak: {user_message}",
            "agent_id": agent_id,
            "session_id": session_id,
            "user_id": user_id,
            "context": context,
        }

    app.state.agent_invoke_fn = fake_agent_invoke_fn
    yield


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
    assert data["client_secret"] == "ek_test"


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


def test_tool_call_invokes_agent_one_adapter():
    from apps.api.main import app

    client = TestClient(app)
    create_resp = client.post(
        "/voice/session",
        json={"agent_id": "agent_one", "user_id": "user_456"},
    )
    session_id = create_resp.json()["session_id"]

    resp = client.post(
        f"/voice/session/{session_id}/tool-call",
        json={
            "tool_name": "run_agent",
            "args": {
                "user_message": "What is the refund policy?",
                "context": {"website_id": "site_123"},
            },
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "answer: What is the refund policy?"
    assert data["speak"] == "speak: What is the refund policy?"
    assert data["agent_id"] == "agent_one"
    assert data["session_id"] == session_id
    assert data["user_id"] == "user_456"
    assert data["context"] == {"website_id": "site_123"}
