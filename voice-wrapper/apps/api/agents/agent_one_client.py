"""HTTP client for invoking agent-one."""
from typing import Any

import httpx

from apps.api.config import Settings


class AgentInvokeError(RuntimeError):
    pass


_AGENT_ROUTES: dict[str, str] = {
    "agent_one":   "/agents/agent-one/invoke",
    "agent-one":   "/agents/agent-one/invoke",
    "l1_support":  "/agents/l1-support/invoke",
    "l1-support":  "/agents/l1-support/invoke",
}


class AgentOneClient:
    def __init__(self, settings: Settings, timeout_seconds: float = 15.0) -> None:
        self._base_url = settings.agent_one_base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def invoke(
        self,
        *,
        agent_id: str,
        user_message: str,
        session_id: str,
        user_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        route = _AGENT_ROUTES.get(agent_id)
        if not route:
            raise AgentInvokeError(f"Unsupported agent_id '{agent_id}'. Known agents: {list(_AGENT_ROUTES)}")

        payload: dict[str, Any] = {
            "message": user_message,
            "thread_id": session_id,
        }
        if user_id is not None:
            payload["user_id"] = user_id
        if context is not None:
            payload["context"] = context

        url = f"{self._base_url}{route}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise AgentInvokeError(
                f"agent-one request timed out after {self._timeout_seconds}s"
            ) from exc
        except httpx.ConnectError as exc:
            raise AgentInvokeError(
                f"agent-one is unreachable at {self._base_url} — is the service running?"
            ) from exc
        except httpx.HTTPError as exc:
            raise AgentInvokeError(f"agent-one HTTP error: {exc}") from exc

        if response.status_code >= 400:
            raise AgentInvokeError(
                f"agent-one invoke failed with HTTP {response.status_code}: {response.text}"
            )

        body = response.json()
        answer = body.get("answer")
        if not isinstance(answer, str):
            raise AgentInvokeError(
                f"agent-one response missing required string 'answer' field; got: {body}"
            )
        speak = body.get("speak") or answer
        return {**body, "answer": answer, "speak": speak}
