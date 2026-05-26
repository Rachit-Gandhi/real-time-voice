"""Tests for SessionManager."""
import pytest
from apps.api.realtime.session_manager import SessionManager


@pytest.fixture
def mgr():
    return SessionManager()


def test_create_returns_session(mgr):
    session = mgr.create(agent_id="agent_one", user_id="user_1")
    assert session["agent_id"] == "agent_one"
    assert session["user_id"] == "user_1"
    assert session["status"] == "active"
    assert isinstance(session["session_id"], str) and session["session_id"]
    assert session["started_at"] is not None
    assert session["last_transcript"] is None


def test_get_returns_created_session(mgr):
    session = mgr.create(agent_id="agent_one", user_id="u1")
    fetched = mgr.get(session["session_id"])
    assert fetched["session_id"] == session["session_id"]


def test_get_unknown_raises_key_error(mgr):
    with pytest.raises(KeyError):
        mgr.get("nonexistent-id")


def test_end_sets_status(mgr):
    session = mgr.create(agent_id="agent_one", user_id="u1")
    sid = session["session_id"]
    result = mgr.end(sid)
    assert result["status"] == "ended"
    assert mgr.get(sid)["status"] == "ended"


def test_end_unknown_raises_key_error(mgr):
    with pytest.raises(KeyError):
        mgr.end("nonexistent-id")


def test_update_transcript(mgr):
    session = mgr.create(agent_id="agent_one", user_id="u1")
    sid = session["session_id"]
    mgr.update_transcript(sid, "Hello there")
    assert mgr.get(sid)["last_transcript"] == "Hello there"
