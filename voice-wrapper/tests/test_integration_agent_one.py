"""Integration tests against a live local agent-one service.

These tests are skipped by default. Run with:
    uv run --extra dev pytest tests/test_integration_agent_one.py --run-integration -v

Requirements:
    - agent-one running at AGENT_ONE_BASE_URL (default: http://localhost:8001)
    - A valid thread_id/session_id the agent can use
"""
import pytest

from apps.api.agents.agent_one_client import AgentOneClient, AgentInvokeError
from apps.api.config import get_settings

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def require_integration_flag(request):
    if not request.config.getoption("--run-integration"):
        pytest.skip("live integration test — pass --run-integration to enable")


@pytest.fixture
def client():
    settings = get_settings()
    return AgentOneClient(settings, timeout_seconds=30.0)


async def test_live_invoke_returns_answer(client):
    result = await client.invoke(
        agent_id="agent_one",
        user_message="What services do you offer?",
        session_id="integration-test-session",
    )
    assert isinstance(result.get("answer"), str) and result["answer"]
    assert isinstance(result.get("speak"), str) and result["speak"]


async def test_live_invoke_with_context(client):
    result = await client.invoke(
        agent_id="agent_one",
        user_message="Tell me about your refund policy.",
        session_id="integration-test-session",
        context={"website_id": "test-site"},
    )
    assert isinstance(result.get("answer"), str)


async def test_live_agent_one_unavailable_gives_clear_error():
    """When agent-one is unreachable the error message is human-readable."""
    from apps.api.config import Settings

    client = AgentOneClient(
        Settings(agent_one_base_url="http://localhost:19999"),
        timeout_seconds=3.0,
    )
    with pytest.raises(AgentInvokeError, match="unreachable"):
        await client.invoke(
            agent_id="agent_one",
            user_message="hello",
            session_id="s1",
        )
