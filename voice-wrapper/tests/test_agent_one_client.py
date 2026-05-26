"""Tests for agent-one HTTP client."""
import pytest
import httpx

from apps.api.agents.agent_one_client import AgentOneClient, AgentInvokeError
from apps.api.config import Settings


@pytest.mark.asyncio
async def test_agent_one_client_posts_invoke_payload(monkeypatch):
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = request.read().decode()
        return httpx.Response(
            200,
            json={"answer": "Full answer", "speak": "Voice answer", "citations": []},
        )

    transport = httpx.MockTransport(handler)

    class MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    client = AgentOneClient(Settings(agent_one_base_url="http://agent-one.test"))
    result = await client.invoke(
        agent_id="agent_one",
        user_message="What services do you offer?",
        session_id="session_1",
        user_id="user_1",
        context={"website_id": "site_1"},
    )

    assert captured["url"] == "http://agent-one.test/agents/agent-one/invoke"
    assert '"message":"What services do you offer?"' in captured["json"]
    assert '"thread_id":"session_1"' in captured["json"]
    assert '"user_id":"user_1"' in captured["json"]
    assert '"website_id":"site_1"' in captured["json"]
    assert result == {"answer": "Full answer", "speak": "Voice answer", "citations": []}


@pytest.mark.asyncio
async def test_agent_one_client_defaults_speak_to_answer(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answer": "Full answer"})

    transport = httpx.MockTransport(handler)

    class MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    client = AgentOneClient(Settings())
    result = await client.invoke(
        agent_id="agent_one",
        user_message="Hello",
        session_id="session_1",
    )

    assert result["speak"] == "Full answer"


def _mock_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    class MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)


@pytest.mark.asyncio
async def test_agent_one_client_raises_on_connect_error(monkeypatch):
    async def handler(request: httpx.Request):
        raise httpx.ConnectError("Connection refused")

    _mock_client(monkeypatch, handler)
    client = AgentOneClient(Settings(agent_one_base_url="http://localhost:8001"))
    with pytest.raises(AgentInvokeError, match="unreachable"):
        await client.invoke(agent_id="agent_one", user_message="hi", session_id="s1")


@pytest.mark.asyncio
async def test_agent_one_client_raises_on_timeout(monkeypatch):
    async def handler(request: httpx.Request):
        raise httpx.TimeoutException("timed out")

    _mock_client(monkeypatch, handler)
    client = AgentOneClient(Settings(), timeout_seconds=5.0)
    with pytest.raises(AgentInvokeError, match="timed out"):
        await client.invoke(agent_id="agent_one", user_message="hi", session_id="s1")


@pytest.mark.asyncio
async def test_agent_one_client_raises_on_http_error_status(monkeypatch):
    async def handler(request: httpx.Request):
        return httpx.Response(503, text="Service Unavailable")

    _mock_client(monkeypatch, handler)
    client = AgentOneClient(Settings())
    with pytest.raises(AgentInvokeError, match="503"):
        await client.invoke(agent_id="agent_one", user_message="hi", session_id="s1")


@pytest.mark.asyncio
async def test_agent_one_client_raises_on_missing_answer(monkeypatch):
    async def handler(request: httpx.Request):
        return httpx.Response(200, json={"speak": "something but no answer"})

    _mock_client(monkeypatch, handler)
    client = AgentOneClient(Settings())
    with pytest.raises(AgentInvokeError, match="answer"):
        await client.invoke(agent_id="agent_one", user_message="hi", session_id="s1")


@pytest.mark.asyncio
async def test_agent_one_client_rejects_unknown_agent_id():
    client = AgentOneClient(Settings())
    with pytest.raises(AgentInvokeError, match="Unsupported agent_id"):
        await client.invoke(agent_id="other_agent", user_message="hi", session_id="s1")
