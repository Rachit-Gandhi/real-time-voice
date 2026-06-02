"""Direct agent invoker — calls agent route functions without an HTTP hop."""
import asyncio
import pathlib
import sys
from typing import Any

from app.routes.agent_one import InvokeRequest, invoke as _agent_one_invoke
from app.routes.l1_support import L1InvokeRequest, l1_invoke as _l1_invoke
from apps.api.agents.agent_one_client import AgentInvokeError

# Make wwts-agent package importable — append, never prepend, to avoid
# shadowing server/main.py when uvicorn searches sys.path for the 'main' module.
_WWTS_AGENT_DIR = str(pathlib.Path(__file__).resolve().parent.parent.parent / "wwts-agent")
if _WWTS_AGENT_DIR not in sys.path:
    sys.path.append(_WWTS_AGENT_DIR)


def _get_wwts_invoke():
    from routes.wwts_agent import WWTSInvokeRequest, wwts_invoke
    return WWTSInvokeRequest, wwts_invoke


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

        if agent_id in ("wwts", "wwts_agent"):
            WWTSInvokeRequest, wwts_invoke = _get_wwts_invoke()
            req = WWTSInvokeRequest(
                message=user_message,
                thread_id=session_id,
                user_id=user_id,
                context=context or {},
            )
            result = await asyncio.to_thread(wwts_invoke, req)
            speak = result.get("speak") or result.get("answer", "")
            return {**result, "speak": speak}

        raise AgentInvokeError(
            f"Unsupported agent_id '{agent_id}'. Known agents: agent_one, l1_support, wwts"
        )
