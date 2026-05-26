"""Tool router for dispatching named tool calls to registered handlers."""
from typing import Any, Callable


class ToolRouter:
    def __init__(self, agent_invoke_fn: Callable) -> None:
        self._agent_invoke_fn = agent_invoke_fn

    def dispatch(self, tool_name: str, args: dict) -> Any:
        if tool_name == "run_agent":
            return self._agent_invoke_fn(
                agent_id=args.get("agent_id"),
                user_message=args.get("user_message"),
                session_id=args.get("session_id"),
            )
        raise ValueError(f"Unknown tool: '{tool_name}'")
