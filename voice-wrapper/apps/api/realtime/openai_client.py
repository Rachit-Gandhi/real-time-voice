"""OpenAI Realtime session creation client."""
from typing import Any

import httpx

from apps.api.config import Settings


class RealtimeSessionError(RuntimeError):
    pass


# Full Realtime API tool definition for each supported tool name.
_TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "run_agent": {
        "type": "function",
        "name": "run_agent",
        "description": (
            "Route the user's question to the back-end knowledge agent. "
            "Use for website, product, pricing, SQL, business, and hybrid questions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "user_message": {
                    "type": "string",
                    "description": "The user's question verbatim",
                },
                "context": {
                    "type": "object",
                    "description": "Optional context key-value pairs (e.g. {\"website_id\": \"site_1\"})",
                },
            },
            "required": ["user_message"],
        },
    },
}


class OpenAIRealtimeClient:
    def __init__(
        self,
        settings: Settings,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._settings = settings
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def create_client_secret(
        self,
        *,
        instructions: str,
        tools: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self._settings.openai_api_key:
            raise RealtimeSessionError("OPENAI_API_KEY is required to create Realtime sessions")

        tool_defs = [
            _TOOL_DEFINITIONS[name]
            for name in (tools or [])
            if name in _TOOL_DEFINITIONS
        ]

        session_cfg: dict[str, Any] = {
            "type": "realtime",
            "model": self._settings.realtime_model,
            "instructions": instructions,
            "audio": {
                "input": {
                    "transcription": {"model": "whisper-1"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.85,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 1200,
                    },
                },
                "output": {
                    "voice": self._settings.realtime_voice,
                },
            },
        }
        if tool_defs:
            session_cfg["tools"] = tool_defs
            session_cfg["tool_choice"] = "auto"

        payload: dict[str, Any] = {
            "expires_after": {
                "anchor": "created_at",
                "seconds": self._settings.realtime_client_secret_ttl_seconds,
            },
            "session": session_cfg,
        }

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._base_url}/realtime/client_secrets",
                headers={
                    "Authorization": f"Bearer {self._settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code >= 400:
            raise RealtimeSessionError(
                f"OpenAI Realtime session creation failed with status {response.status_code}: "
                f"{response.text}"
            )
        return response.json()
