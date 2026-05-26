"""Session state management for voice sessions."""
import uuid
from datetime import datetime


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}

    def create(self, agent_id: str, user_id: str) -> dict:
        session_id = str(uuid.uuid4())
        session = {
            "session_id": session_id,
            "agent_id": agent_id,
            "user_id": user_id,
            "status": "active",
            "started_at": datetime.utcnow().isoformat(),
            "last_transcript": None,
            "active_tool_call": None,
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
