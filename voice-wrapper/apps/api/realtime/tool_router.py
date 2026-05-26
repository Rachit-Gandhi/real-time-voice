"""Tool router for dispatching named tool calls to registered handlers."""
from typing import Any, Callable


class ToolRouter:
    def __init__(self, handlers: dict[str, Callable[[dict], Any]]) -> None:
        self._handlers = handlers

    def dispatch(self, tool_name: str, args: dict) -> Any:
        if tool_name not in self._handlers:
            raise ValueError(f"Unknown tool: '{tool_name}'")
        return self._handlers[tool_name](args)
