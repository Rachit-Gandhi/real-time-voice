# voice-wrapper

FastAPI backend for the Voice/Realtime Wrapper (Plan 1).

Creates OpenAI Realtime voice sessions and routes LangGraph tool calls from the session back to registered agents.

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```
