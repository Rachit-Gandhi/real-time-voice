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
                    "You are a voice assistant. When the user speaks, call run_agent IMMEDIATELY "
                    "with their exact spoken words as user_message — do not paraphrase or modify. "
                    "Use run_agent for ANY business question: website, products, pricing, policies, data, operations. "
                    "Reply directly ONLY for greetings or to ask for clarification when speech is unclear. "
                    "After calling run_agent, read back the 'speak' field from the result naturally."
                ),
                tools=["run_agent"],
            )
        )
        # Pre-register l1_support
        self.register(
            AgentConfig(
                agent_id="l1_support",
                instructions=(
                    "You are an L1 customer support voice agent. "
                    "ONLY call run_agent when the user describes a problem, complaint, or support issue. "
                    "Do NOT call run_agent for greetings (hi, hello, hey), "
                    "farewells (bye, goodbye, take care, thanks, thank you), "
                    "or short affirmations/negations (yes, no, okay, sure, got it). "
                    "For greetings respond warmly and ask how you can help. "
                    "For farewells say goodbye naturally without calling any tool. "
                    "For everything else, call run_agent immediately with the user's exact words as user_message, "
                    "then follow the agent's instructions about what to ask next."
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
