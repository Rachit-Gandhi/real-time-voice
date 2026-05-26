# voice-wrapper v0.9

FastAPI backend that creates OpenAI Realtime voice sessions and routes `run_agent` tool calls to the agent-one backend.

## Architecture

```
Browser / WebRTC client
        │ (ephemeral client_secret)
        ▼
POST /voice/session  ──► OpenAI /v1/realtime/client_secrets
                                │
                                ▼ (Realtime session w/ run_agent tool registered)
        Browser connects directly to OpenAI Realtime WebSocket
                                │
                    model emits run_agent tool call
                                │
        ▼
POST /voice/session/{id}/tool-call  ──► POST {AGENT_ONE_BASE_URL}/agents/agent-one/invoke
                                │
                                ▼
                    normalized {answer, speak} returned to client
                    client submits tool result back to Realtime
```

## Environment variables

Copy `.env.example` to `.env`:

```dotenv
OPENAI_API_KEY=sk-...
REALTIME_MODEL=gpt-4o-realtime-preview
REALTIME_VOICE=verse
REALTIME_CLIENT_SECRET_TTL_SECONDS=600
AGENT_ONE_BASE_URL=http://localhost:8001
```

| Variable | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | — | Required for real sessions |
| `REALTIME_MODEL` | `gpt-realtime` | OpenAI Realtime model ID |
| `REALTIME_VOICE` | `marin` | Realtime voice name |
| `REALTIME_CLIENT_SECRET_TTL_SECONDS` | `600` | Ephemeral key TTL (max 3600) |
| `AGENT_ONE_BASE_URL` | `http://localhost:8001` | agent-one service base URL |

## Start services

**1. Start agent-one** (separate terminal, from the agent-one repo):

```powershell
cd D:\rtv-agent-one\agent-one
uv run uvicorn apps.api.main:app --port 8001 --reload
```

**2. Start voice-wrapper** (from this directory):

```powershell
cd D:\rtv-voice-wrapper\voice-wrapper
uv run uvicorn apps.api.main:app --port 8000 --reload
```

## Verify the voice-to-agent flow

### 1. Create a voice session

```powershell
curl -s -X POST http://localhost:8000/voice/session `
  -H "Content-Type: application/json" `
  -d '{"agent_id": "agent_one", "user_id": "user_123"}' | ConvertFrom-Json
```

Expected response:
```json
{
  "session_id": "3fa85f64-...",
  "agent_id": "agent_one",
  "user_id": "user_123",
  "status": "active",
  "started_at": "2026-05-26T...",
  "client_secret": "ek_...",
  "realtime": { "session": { ... }, "expires_at": ... },
  ...
}
```

The `client_secret` value is the ephemeral key your browser passes to the OpenAI Realtime WebSocket.

### 2. Simulate a run_agent tool call

Replace `SESSION_ID` with the value from step 1:

```powershell
curl -s -X POST http://localhost:8000/voice/session/SESSION_ID/tool-call `
  -H "Content-Type: application/json" `
  -d '{
    "tool_name": "run_agent",
    "args": {
      "user_message": "What is your refund policy?",
      "context": {"website_id": "site_123"}
    }
  }' | ConvertFrom-Json
```

Expected response (when agent-one is running):
```json
{
  "answer": "Our refund policy is...",
  "speak": "Our refund policy is...",
  "citations": [...]
}
```

### 3. Verify error handling when agent-one is unavailable

Stop agent-one, then repeat step 2. You should get a 502 with a clear message:

```json
{
  "detail": "agent-one is unreachable at http://localhost:8001 — is the service running?"
}
```

### 4. Session status and cleanup

```powershell
# Check session state
curl http://localhost:8000/voice/session/SESSION_ID/status

# End session
curl -X POST http://localhost:8000/voice/session/SESSION_ID/end
```

## Running tests

```powershell
# Unit tests (no API keys or running services required)
uv run --extra dev pytest tests/ -v

# Integration tests against live local services
uv run --extra dev pytest tests/test_integration_agent_one.py --run-integration -v
```

## agent-one invoke contract

`POST {AGENT_ONE_BASE_URL}/agents/agent-one/invoke`

Request:
```json
{
  "message": "<user question>",
  "thread_id": "<session_id>",
  "user_id": "<optional>",
  "context": { "<optional key-value pairs>" }
}
```

Response (expected):
```json
{
  "answer": "<full answer string>",
  "speak": "<voice-optimised answer, defaults to answer if absent>",
  "citations": []
}
```

The `answer` field is required. If absent, voice-wrapper returns a 502 with a descriptive error.

## Known gaps / v1.0 work

- **No server-side sideband WebSocket**: The current path requires the browser to call `POST /tool-call` and inject the result back into the Realtime session. A full v1.0 would open a server-side WebSocket to the Realtime API (see `sideband.py` stub) so the backend can intercept and fulfil tool calls automatically.
- **No authentication**: All endpoints are unauthenticated.
- **Single agent**: Only `agent_one` is registered. Adding more agents requires extending `AgentRegistry` and mapping their tool names in `openai_client._TOOL_DEFINITIONS`.
- **Realtime model name**: Update `REALTIME_MODEL` to the exact model ID from your OpenAI dashboard (e.g. `gpt-4o-realtime-preview-2024-12-17`).
