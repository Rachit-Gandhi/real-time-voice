"""Agent registry for managing registered agents."""
from pydantic import BaseModel


class AgentConfig(BaseModel):
    agent_id: str
    instructions: str
    tools: list[str]


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentConfig] = {}
        # Pre-register agent_one
        self.register(
            AgentConfig(
                agent_id="agent_one",
                instructions="Answer using website data and approved backend tools.",
                tools=["run_agent"],
            )
        )

    def register(self, config: AgentConfig) -> None:
        self._agents[config.agent_id] = config

    def get(self, agent_id: str) -> AgentConfig:
        if agent_id not in self._agents:
            raise KeyError(f"Agent '{agent_id}' not found in registry")
        return self._agents[agent_id]
