"""Direct agent invoker — calls agent route functions without an HTTP hop."""
import asyncio
from typing import Any

from app.routes.agent_one import InvokeRequest, invoke as _agent_one_invoke
from app.routes.l1_support import L1InvokeRequest, l1_invoke as _l1_invoke
from apps.api.agents.agent_one_client import AgentInvokeError


class DirectAgentInvoker:
    async def invoke(
        self,
        *,
        agent_id: str,
        user_message: str,
        session_id: str,
        user_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if agent_id in ("agent_one", "agent-one"):
            req = InvokeRequest(
                message=user_message,
                thread_id=session_id,
                user_id=user_id,
                context=context or {},
            )
            result = await asyncio.to_thread(_agent_one_invoke, req)
            speak = result.get("speak") or result.get("answer", "")
            return {**result, "speak": speak}

        if agent_id in ("l1_support", "l1-support"):
            req = L1InvokeRequest(
                message=user_message,
                thread_id=session_id,
                user_id=user_id,
                context=context or {},
            )
            result = await asyncio.to_thread(_l1_invoke, req)
            speak = result.get("speak") or result.get("answer", "")
            return {**result, "speak": speak}

        raise AgentInvokeError(
            f"Unsupported agent_id '{agent_id}'. Known agents: agent_one, l1_support"
        )
