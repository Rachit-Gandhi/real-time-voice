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
                    "You are a voice assistant backed by a knowledge agent. "
                    "Call run_agent with the user's EXACT spoken words for every substantive message. "
                    "After calling run_agent, read back the 'speak' field from the result naturally — "
                    "do not add, remove, or paraphrase anything.\n\n"
                    "The ONLY times you may respond without calling run_agent:\n"
                    "  - Pure opening greeting ('hi', 'hello') with no question — greet back briefly.\n"
                    "  - Speech is genuinely unintelligible — ask the user to repeat.\n\n"
                    "Never answer business questions, website questions, or product questions from "
                    "your own knowledge — always route through run_agent."
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
                    "Your ONLY job is to relay every user message to the backend via run_agent "
                    "and then read back the 'speak' field from the result verbatim. "
                    "Do NOT add your own diagnosis, advice, or commentary.\n\n"
                    "WHEN to skip run_agent (the only two exceptions):\n"
                    "  - The very first message is a pure greeting with no issue mentioned "
                    "(e.g. 'hi', 'hello') — respond warmly and ask how you can help.\n"
                    "  - The user says only a farewell ('bye', 'goodbye', 'thanks') AFTER "
                    "the backend has already confirmed a ticket is filed — say goodbye naturally.\n\n"
                    "ALWAYS call run_agent for:\n"
                    "  - Any description of a problem or issue.\n"
                    "  - Any answer to a troubleshooting question, even a one-word answer "
                    "like 'yes', 'no', 'done', 'it still doesn't work'.\n"
                    "  - Any follow-up detail while an active support conversation is in progress.\n"
                    "  - Confirmations, affirmations, or clarifications mid-conversation.\n\n"
                    "KEY RULE: once a support conversation has started (run_agent was called at "
                    "least once), EVERY subsequent user message must go through run_agent — "
                    "never skip it because a message seems short or obvious."
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
