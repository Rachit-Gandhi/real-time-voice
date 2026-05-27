"""Tests for OpenAI Realtime client."""
import pytest
import httpx

from apps.api.config import Settings
from apps.api.realtime.openai_client import OpenAIRealtimeClient, RealtimeSessionError


@pytest.mark.asyncio
async def test_create_client_secret_posts_realtime_session(monkeypatch):
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["json"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "expires_at": 123,
                "value": "ek_test",
                "session": {
                    "type": "realtime",
                },
            },
        )

    transport = httpx.MockTransport(handler)

    class MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
    client = OpenAIRealtimeClient(
        Settings(
            openai_api_key="sk_test",
            realtime_model="gpt-realtime",
            realtime_voice="verse",
            realtime_client_secret_ttl_seconds=300,
        )
    )

    result = await client.create_client_secret(instructions="Answer briefly.")

    assert result["value"] == "ek_test"
    assert captured["url"] == "https://api.openai.com/v1/realtime/client_secrets"
    assert captured["authorization"] == "Bearer sk_test"
    assert '"type":"realtime"' in captured["json"]
    assert '"model":"gpt-realtime"' in captured["json"]
    assert '"instructions":"Answer briefly."' in captured["json"]


@pytest.mark.asyncio
async def test_create_client_secret_requires_api_key():
    client = OpenAIRealtimeClient(Settings(openai_api_key=None))
    with pytest.raises(RealtimeSessionError):
        await client.create_client_secret(instructions="x")


@pytest.mark.asyncio
async def test_create_client_secret_includes_run_agent_tool(monkeypatch):
    import json

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json={"expires_at": 123, "value": "ek_test", "session": {}})

    transport = httpx.MockTransport(handler)

    class MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
    client = OpenAIRealtimeClient(Settings(openai_api_key="sk_test"))

    await client.create_client_secret(instructions="Test.", tools=["run_agent"])

    session = captured["body"]["session"]
    assert "tools" in session, "session must include tools list"
    tool_names = [t["name"] for t in session["tools"]]
    assert "run_agent" in tool_names
    assert session["tool_choice"] == "auto"
    run_agent = next(t for t in session["tools"] if t["name"] == "run_agent")
    assert run_agent["type"] == "function"
    assert "user_message" in run_agent["parameters"]["properties"]
    assert "user_message" in run_agent["parameters"]["required"]


@pytest.mark.asyncio
async def test_create_client_secret_no_tools_omits_tools_key(monkeypatch):
    import json

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json={"expires_at": 123, "value": "ek_test", "session": {}})

    transport = httpx.MockTransport(handler)

    class MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            super().__init__(transport=transport)

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)
    client = OpenAIRealtimeClient(Settings(openai_api_key="sk_test"))

    await client.create_client_secret(instructions="Test.")

    session = captured["body"]["session"]
    assert "tools" not in session
    assert "tool_choice" not in session
