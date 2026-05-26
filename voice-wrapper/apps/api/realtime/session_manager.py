"""Session state management for voice sessions."""
import uuid
from datetime import UTC, datetime

from apps.api.agents.registry import AgentRegistry


class SessionManager:
    def __init__(self, *, realtime_client=None, registry: AgentRegistry | None = None) -> None:
        self._sessions: dict[str, dict] = {}
        self._realtime_client = realtime_client
        self._registry = registry or AgentRegistry()

    async def create(self, agent_id: str, user_id: str) -> dict:
        agent_config = self._registry.get(agent_id)
        realtime_session = None
        client_secret = None
        if self._realtime_client is not None:
            realtime_session = await self._realtime_client.create_client_secret(
                instructions=agent_config.instructions,
                tools=agent_config.tools,
            )
            client_secret = realtime_session.get("value") or (
                realtime_session.get("session", {})
                .get("client_secret", {})
                .get("value")
            )

        session_id = str(uuid.uuid4())
        session = {
            "session_id": session_id,
            "agent_id": agent_id,
            "user_id": user_id,
            "status": "active",
            "started_at": datetime.now(UTC).isoformat(),
            "last_transcript": None,
            "active_tool_call": None,
            "realtime": realtime_session,
            "client_secret": client_secret,
        }
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> dict:
        if session_id not in self._sessions:
            raise KeyError(f"Session '{session_id}' not found")
        return self._sessions[session_id]

    def end(self, session_id: str) -> dict:
        session = self.get(session_id)
        session["status"] = "ended"
        return {"session_id": session_id, "status": "ended"}

    def update_transcript(self, session_id: str, transcript: str) -> None:
        session = self.get(session_id)
        session["last_transcript"] = transcript
