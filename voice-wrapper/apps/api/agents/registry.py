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
                instructions=(
                    "You are a voice assistant for a business. "
                    "For ANY question about the website, products, pricing, company information, "
                    "policies, FAQs, SQL data, business operations, or hybrid topics, "
                    "you MUST call the run_agent tool with the user's question verbatim. "
                    "Do not answer those questions from your own knowledge — always delegate to run_agent. "
                    "You may respond directly only for simple greetings, "
                    "clarifications about what you can help with, or small talk."
                ),
                tools=["run_agent"],
            )
        )

    def register(self, config: AgentConfig) -> None:
        self._agents[config.agent_id] = config

    def get(self, agent_id: str) -> AgentConfig:
        if agent_id not in self._agents:
            raise KeyError(f"Agent '{agent_id}' not found in registry")
        return self._agents[agent_id]
