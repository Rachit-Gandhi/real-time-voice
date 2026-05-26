"""Tool router for dispatching named tool calls to registered handlers."""
import inspect
from typing import Any, Callable


class ToolRouter:
    def __init__(self, agent_invoke_fn: Callable) -> None:
        self._agent_invoke_fn = agent_invoke_fn

    async def dispatch(self, tool_name: str, args: dict) -> Any:
        if tool_name == "run_agent":
            result = self._agent_invoke_fn(
                agent_id=args.get("agent_id"),
                user_message=args.get("user_message"),
                session_id=args.get("session_id"),
                user_id=args.get("user_id"),
                context=args.get("context"),
            )
            if inspect.isawaitable(result):
                return await result
            return result
        raise ValueError(f"Unknown tool: '{tool_name}'")
