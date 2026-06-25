"""Tests for SidebandConnection stub."""
from apps.api.realtime.sideband import SidebandConnection


def test_initial_state_disconnected():
    conn = SidebandConnection(session_id="s1", realtime_session_token="tok123")
    assert conn.session_id == "s1"
    assert not conn.is_connected


def test_connect_sets_connected():
    conn = SidebandConnection(session_id="s1", realtime_session_token="tok")
    conn.connect()
    assert conn.is_connected


def test_disconnect_unsets_connected():
    conn = SidebandConnection(session_id="s1", realtime_session_token="tok")
    conn.connect()
    conn.disconnect()
    assert not conn.is_connected
