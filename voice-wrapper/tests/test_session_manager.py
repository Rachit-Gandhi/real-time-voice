"""Tests for SessionManager."""
import pytest
from apps.api.realtime.session_manager import SessionManager


class FakeRealtimeClient:
    def __init__(self):
        self.instructions = None
        self.tools = None

    async def create_client_secret(self, *, instructions: str, tools=None):
        self.instructions = instructions
        self.tools = tools
        return {
            "expires_at": 123,
            "value": "ek_test",
            "session": {
                "type": "realtime",
            },
        }


@pytest.fixture
def mgr():
    return SessionManager(realtime_client=FakeRealtimeClient())


@pytest.mark.asyncio
async def test_create_returns_session(mgr):
    session = await mgr.create(agent_id="agent_one", user_id="user_1")
    assert session["agent_id"] == "agent_one"
    assert session["user_id"] == "user_1"
    assert session["status"] == "active"
    assert isinstance(session["session_id"], str) and session["session_id"]
    assert session["started_at"] is not None
    assert session["last_transcript"] is None
    assert session["client_secret"] == "ek_test"
    assert session["realtime"]["session"]["type"] == "realtime"


@pytest.mark.asyncio
async def test_get_returns_created_session(mgr):
    session = await mgr.create(agent_id="agent_one", user_id="u1")
    fetched = mgr.get(session["session_id"])
    assert fetched["session_id"] == session["session_id"]


def test_get_unknown_raises_key_error(mgr):
    with pytest.raises(KeyError):
        mgr.get("nonexistent-id")


@pytest.mark.asyncio
async def test_end_sets_status(mgr):
    session = await mgr.create(agent_id="agent_one", user_id="u1")
    sid = session["session_id"]
    result = mgr.end(sid)
    assert result["status"] == "ended"
    assert mgr.get(sid)["status"] == "ended"


def test_end_unknown_raises_key_error(mgr):
    with pytest.raises(KeyError):
        mgr.end("nonexistent-id")


@pytest.mark.asyncio
async def test_update_transcript(mgr):
    session = await mgr.create(agent_id="agent_one", user_id="u1")
    sid = session["session_id"]
    mgr.update_transcript(sid, "Hello there")
    assert mgr.get(sid)["last_transcript"] == "Hello there"


@pytest.mark.asyncio
async def test_create_passes_tools_to_realtime_client():
    fake = FakeRealtimeClient()
    mgr = SessionManager(realtime_client=fake)
    await mgr.create(agent_id="agent_one", user_id="u1")
    assert fake.tools == ["run_agent"]


@pytest.mark.asyncio
async def test_create_stores_context(mgr):
    ctx = {"wwts_session": 45270812, "env": "QA"}
    session = await mgr.create(agent_id="agent_one", user_id="dpscript", context=ctx)
    assert session["context"] == ctx
    assert mgr.get(session["session_id"])["context"] == ctx


@pytest.mark.asyncio
async def test_create_without_context_defaults_empty(mgr):
    session = await mgr.create(agent_id="agent_one", user_id="u1")
    assert session["context"] == {}
    mgr = SessionManager(realtime_client=None)
    session = await mgr.create(agent_id="agent_one", user_id="u1")
    assert session["client_secret"] is None
    assert session["realtime"] is None
