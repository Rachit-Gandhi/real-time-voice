"""Tests for agent registry."""
import pytest


def test_registry_get_agent_one():
    """registry.get('agent_one') returns config with required fields."""
    from apps.api.agents.registry import AgentRegistry

    registry = AgentRegistry()
    config = registry.get("agent_one")
    assert config.agent_id == "agent_one"
    assert isinstance(config.instructions, str) and config.instructions != ""
    assert isinstance(config.tools, list)


def test_registry_get_nonexistent_raises():
    """registry.get('nonexistent') raises KeyError."""
    from apps.api.agents.registry import AgentRegistry

    registry = AgentRegistry()
    with pytest.raises(KeyError):
        registry.get("nonexistent")


def test_registry_register_and_get():
    """registry.register adds a new agent retrievable via registry.get."""
    from apps.api.agents.registry import AgentRegistry, AgentConfig

    registry = AgentRegistry()
    new_agent = AgentConfig(
        agent_id="test_agent",
        instructions="Test instructions.",
        tools=["some_tool"],
    )
    registry.register(new_agent)
    result = registry.get("test_agent")
    assert result.agent_id == "test_agent"
    assert result.instructions == "Test instructions."
    assert result.tools == ["some_tool"]
