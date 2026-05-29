"""Session state management for voice sessions."""
import uuid
from datetime import UTC, datetime

from apps.api.agents.registry import AgentRegistry


class SessionManager:
    def __init__(self, *, realtime_client=None, registry: AgentRegistry | None = None) -> None:
        self._sessions: dict[str, dict] = {}
        self._realtime_client = realtime_client
        self._registry = registry or AgentRegistry()

    async def create(
        self,
        agent_id: str,
        user_id: str,
        context: dict | None = None,
    ) -> dict:
        agent_config = self._registry.get(agent_id)
        realtime_session = None
        client_secret = None
        if self._realtime_client is not None:
            realtime_session = await self._realtime_client.create_client_secret(
                instructions=agent_config.instructions,
                tools=agent_config.tools,
            )
            # GA client_secrets returns client_secret as string or {value, expires_at}
            cs = realtime_session.get("client_secret")
            if isinstance(cs, dict):
                client_secret = cs.get("value")
            elif isinstance(cs, str):
                client_secret = cs
            else:
                client_secret = realtime_session.get("value")

        session_id = str(uuid.uuid4())
        session = {
            "session_id": session_id,
            "agent_id": agent_id,
            "user_id": user_id,
            "context": context or {},
            "status": "active",
            "started_at": datetime.now(UTC).isoformat(),
            "last_transcript": None,
            "transcript": [],
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

    def add_turn(self, session_id: str, user_message: str, agent_response: str) -> None:
        session = self.get(session_id)
        ts = datetime.now(UTC).isoformat()
        session["last_transcript"] = user_message
        session["transcript"].append({"role": "user", "text": user_message, "ts": ts})
        session["transcript"].append({"role": "assistant", "text": agent_response, "ts": ts})
