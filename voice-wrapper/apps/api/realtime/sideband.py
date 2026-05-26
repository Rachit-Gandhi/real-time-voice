"""Sideband server-side control connection for OpenAI Realtime sessions."""


class SidebandConnection:
    """Manages server-side control over an OpenAI Realtime session.

    In production this would hold a WebSocket to the Realtime API so the
    backend can send server events (session.update, input_audio_buffer.clear,
    response.cancel) without going through the browser.
    """

    def __init__(self, session_id: str, realtime_session_token: str) -> None:
        self.session_id = session_id
        self._token = realtime_session_token
        self._connected = False

    def connect(self) -> None:
        """Stub: would open a WebSocket to the OpenAI Realtime API."""
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected
