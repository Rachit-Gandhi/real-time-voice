Below are **two separate but compatible plans**.

The important separation:

```text
Plan 1: Voice / Realtime Wrapper
Purpose: turns any LangGraph agent into a voice agent.

Plan 2: Agent One
Purpose: actual LangGraph + toolset agent that answers from scraped website data or SQL/backend APIs.
```

OpenAI’s current Realtime docs recommend WebRTC for browser/mobile voice sessions, while keeping private tool/business logic on your backend through server-side controls or sideband connections. Realtime sessions support speech-to-speech interaction and function calling, while WebSockets are more useful for server-side/manual audio handling. ([OpenAI Platform][1])

---

# Plan 1 — Voice / Realtime Wrapper for Any LangGraph Agent

## 1. Objective

Build a reusable wrapper that can expose **any LangGraph agent** as a low-latency voice assistant.

It should not care whether the underlying agent is:

```text
website Q&A agent
SQL agent
CRM agent
calendar booking agent
legal drafting agent
support agent
internal company knowledge agent
```

The wrapper’s job is only:

```text
voice input → realtime session → tool call → LangGraph backend → spoken output
```

---

## 2. Core architecture

```text
Browser / Mobile Client
  ↓ WebRTC audio
OpenAI Realtime Session
  ↕ data channel / sideband
Voice Wrapper Backend
  ↓
LangGraph Agent Registry
  ↓
Selected LangGraph Agent
  ↓
Tools / APIs / DB / Vector Store
```

For phone later:

```text
Phone Call
  ↓ SIP / Twilio / LiveKit SIP
OpenAI Realtime
  ↕ sideband backend
Voice Wrapper Backend
  ↓
LangGraph Agent
```

---

## 3. Main components

### A. Client SDK

Create a small frontend package:

```text
@your-org/voice-client
```

Responsibilities:

```text
startVoiceSession(agentId)
stopVoiceSession()
mute/unmute
interrupt response
display live transcript
display tool-call status
send text fallback
```

Frontend tech:

```text
Next.js / React
WebRTC
OpenAI Realtime data channel
```

Client API example:

```ts
const session = await voiceClient.start({
  agentId: "agent_one",
  userId: "user_123",
  context: {
    pageUrl: window.location.href,
    mode: "website_qa"
  }
});
```

---

### B. Voice Session Backend

Backend endpoints:

```text
POST /voice/session
POST /voice/session/:id/end
GET  /voice/session/:id/status
```

Responsibilities:

```text
create realtime session
attach agent instructions
create sideband/server control connection
register tools exposed to Realtime
route function calls to LangGraph
persist session metadata
```

Suggested stack:

```text
FastAPI
Postgres
Redis
OpenAI Realtime API
LangGraph
```

---

### C. Agent Registry

This is what makes the wrapper reusable.

```python
AGENT_REGISTRY = {
    "agent_one": AgentConfig(
        graph=agent_one_graph,
        instructions="Answer using website data or SQL tools.",
        tools=["run_agent_one"],
    ),
    "calendar_agent": AgentConfig(...),
    "support_agent": AgentConfig(...),
}
```

The voice wrapper should not import every agent manually. Use a registry pattern.

---

### D. Universal Realtime Tool

Expose only one high-level function to Realtime initially:

```ts
run_agent({
  agent_id: string,
  session_id: string,
  user_message: string,
  conversation_context?: object
})
```

Realtime calls this tool whenever the user asks something requiring backend intelligence.

The backend then routes:

```text
run_agent()
  ↓
load agent config
  ↓
load session state
  ↓
graph.invoke()
  ↓
return speakable answer
```

---

## 4. Realtime session behavior

Voice wrapper should handle:

```text
user interruption / barge-in
turn detection
silence timeout
tool-call pending message
audio response
text transcript
session cancellation
error fallback
```

Example voice instruction:

```text
You are a voice interface for backend LangGraph agents.
Keep spoken answers concise.
When the user asks a factual, account-specific, website-specific, or database-specific question, call run_agent.
Do not invent backend data.
If a tool call is pending, briefly acknowledge and wait.
```

---

## 5. Function-call contract

The LangGraph agent should return a normalized response.

```json
{
  "answer": "The refund status is currently pending because...",
  "speak": "The refund status is currently pending. The latest note says...",
  "confidence": 0.82,
  "sources": [
    {
      "type": "website",
      "title": "Refund Policy",
      "url": "https://example.com/refund"
    }
  ],
  "state_patch": {
    "last_intent": "refund_status"
  },
  "requires_followup": false
}
```

The voice wrapper uses:

```text
speak → spoken response
answer → transcript/chat UI
sources → UI citations
state_patch → session memory
```

---

## 6. State model

Use two levels of state.

### Voice session state

```json
{
  "voice_session_id": "vs_123",
  "agent_id": "agent_one",
  "user_id": "user_123",
  "started_at": "...",
  "last_transcript": "...",
  "active_tool_call": null,
  "status": "active"
}
```

### LangGraph state

```json
{
  "thread_id": "agent_one:user_123:vs_123",
  "messages": [],
  "selected_source": "website",
  "retrieved_docs": [],
  "sql_result": null,
  "final_answer": null
}
```

Do not mix voice transport state with agent reasoning state.

---

## 7. MVP milestones

### Milestone 1 — Text-only LangGraph bridge

Build:

```text
POST /agents/:agent_id/invoke
```

Input:

```json
{
  "message": "What services does this website offer?",
  "thread_id": "test_1"
}
```

Output:

```json
{
  "answer": "...",
  "speak": "..."
}
```

No voice yet.

---

### Milestone 2 — WebRTC voice session

Build:

```text
Start voice session from browser
Realtime speaks basic responses
Realtime can call run_agent
Backend returns LangGraph result
```

---

### Milestone 3 — Sideband/server control

Move private tool execution fully to backend.

Goal:

```text
Browser handles audio only.
Backend handles tool execution.
LangGraph and API keys never touch browser.
```

---

### Milestone 4 — Interruptions and UX

Add:

```text
barge-in
"thinking" indicator
tool-call status
transcript panel
manual text fallback
retry button
session logs
```

---

### Milestone 5 — Agent plug-in system

Add:

```text
agent registry
per-agent instructions
per-agent tools
per-agent state schema
per-agent auth scopes
```

Then any LangGraph agent can become voice-enabled.

---

## 8. Folder structure

```text
voice-wrapper/
  apps/
    web/
      components/
        VoiceButton.tsx
        TranscriptPanel.tsx
      lib/
        voiceClient.ts

    api/
      main.py
      routes/
        voice.py
        agents.py
      realtime/
        session_manager.py
        sideband.py
        tool_router.py
      agents/
        registry.py
      db/
        models.py

  packages/
    voice-client/
    shared-types/
```

---

## 9. Final deliverable of Plan 1

A reusable voice shell:

```text
Any LangGraph agent in registry
  ↓
automatically becomes a voice agent
```

With:

```text
WebRTC frontend
Realtime session creation
sideband backend
tool-call router
LangGraph adapter
session persistence
transcript UI
```

---

# Plan 2 — Agent One: LangGraph + Toolset Agent for Website + SQL/API Q&A

## 1. Objective

Build **Agent One**, a backend LangGraph agent that can answer questions using:

```text
scraped website content
semantic vector search
SQL database queries
backend APIs
```

It should work both as:

```text
text API agent
voice agent through Plan 1 wrapper
```

---

## 2. Core architecture

```text
User Question
  ↓
Agent One LangGraph
  ↓
Intent Router
  ├─ Website semantic search
  ├─ SQL query/API call
  ├─ Hybrid website + SQL
  └─ clarification / fallback
  ↓
Answer Generator
  ↓
Cited response
```

---

## 3. Data ingestion pipeline

### A. Website scraper

Build a crawler:

```text
input: root URL
output: cleaned website documents
```

Capabilities:

```text
crawl sitemap.xml
crawl internal links
respect robots.txt if needed
extract main content
remove navbar/footer boilerplate
save page title, URL, headings, text
deduplicate pages
track last crawled date
```

Suggested tools:

```text
Playwright for JS-heavy sites
BeautifulSoup / trafilatura for static pages
httpx for fast fetching
```

---

### B. Chunking

Chunk documents into semantically useful blocks:

```json
{
  "doc_id": "page_123",
  "url": "https://example.com/pricing",
  "title": "Pricing",
  "heading_path": ["Home", "Pricing"],
  "chunk_text": "Our starter plan includes...",
  "chunk_index": 4,
  "last_crawled_at": "..."
}
```

Chunking strategy:

```text
500–900 tokens per chunk
heading-aware splitting
overlap 80–120 tokens
preserve URL + title metadata
```

---

### C. Embeddings and vector store

Use:

```text
Postgres + pgvector
```

Tables:

```sql
websites
web_pages
web_chunks
crawl_runs
```

Example:

```sql
CREATE TABLE web_chunks (
  id UUID PRIMARY KEY,
  website_id UUID,
  page_id UUID,
  url TEXT,
  title TEXT,
  heading_path TEXT[],
  content TEXT,
  embedding VECTOR,
  last_crawled_at TIMESTAMP
);
```

---

## 4. SQL/API backend access

Agent One should not directly touch production DB tables unless controlled.

Use one of two patterns.

### Safer pattern: API tools

```text
Agent One → backend API → database
```

Example tools:

```text
get_customer_by_email
get_order_status
get_invoice_summary
get_available_slots
get_case_status
```

This is safer and easier to guardrail.

---

### Advanced pattern: SQL tool

```text
Agent One → SQL planner → read-only SQL executor
```

Hard rules:

```text
read-only connection
SELECT only
row limit
query timeout
approved schema only
no INSERT/UPDATE/DELETE/DROP
no raw PII unless authorized
query explanation logged
```

---

## 5. LangGraph state

```python
class AgentOneState(TypedDict):
    user_id: str
    thread_id: str
    user_message: str
    messages: list

    intent: Literal[
        "website_qa",
        "sql_qa",
        "hybrid",
        "clarification",
        "unsupported"
    ]

    website_id: str | None
    retrieved_chunks: list
    sql_query: str | None
    sql_result: list | None
    api_result: dict | None

    draft_answer: str | None
    final_answer: str | None
    speak: str | None
    citations: list
    confidence: float
```

---

## 6. LangGraph nodes

### Node 1 — Normalize input

Purpose:

```text
clean transcript
resolve pronouns from conversation
detect current website/account context
```

---

### Node 2 — Intent router

Routes to:

```text
website_qa
sql_qa
hybrid
clarification
unsupported
```

Examples:

| User asks                                             | Route                |
| ----------------------------------------------------- | -------------------- |
| “What services do they provide?”                      | website_qa           |
| “What is my order status?”                            | sql_qa / API         |
| “Do they offer refunds and what is my refund status?” | hybrid               |
| “Book me for tomorrow”                                | API/tool flow        |
| “Tell me something not on the site”                   | unsupported/fallback |

---

### Node 3 — Website retriever

Input:

```text
question
website_id
```

Output:

```text
top relevant chunks
URLs
titles
confidence
```

Retrieval strategy:

```text
hybrid search = vector + keyword
rerank top 20 to top 5
filter by website_id
prefer recent crawl
```

---

### Node 4 — SQL/API planner

Decides whether to call structured tools.

For MVP, prefer API tools:

```python
tools = [
    get_order_status,
    get_customer_profile,
    get_invoice_summary,
    search_appointments,
]
```

Later add SQL planner:

```text
question → schema-aware SQL → validation → execution → summarized result
```

---

### Node 5 — Answer composer

Rules:

```text
use only retrieved website chunks and approved API/SQL results
cite website URLs
state uncertainty
do not invent missing info
for voice, create shorter speak version
```

Output:

```json
{
  "answer": "According to the Pricing page...",
  "speak": "According to the site, the starter plan includes...",
  "citations": [...],
  "confidence": 0.86
}
```

---

### Node 6 — Fallback / clarification

Ask clarification only when needed:

```text
Which website should I search?
Which customer/order are you referring to?
I could not find that in the website content.
```

---

## 7. Agent One graph

```text
START
  ↓
normalize_input
  ↓
intent_router
  ├─ website_qa → website_retriever → answer_composer
  ├─ sql_qa     → api_or_sql_tool  → answer_composer
  ├─ hybrid     → website_retriever + api_or_sql_tool → answer_composer
  ├─ clarification → clarification_response
  └─ unsupported → fallback_response
  ↓
END
```

---

## 8. Backend API design

### Invoke agent

```http
POST /agents/agent-one/invoke
```

Input:

```json
{
  "thread_id": "thread_123",
  "user_id": "user_123",
  "message": "What is the refund policy?",
  "context": {
    "website_id": "site_123",
    "customer_id": "cust_456"
  }
}
```

Output:

```json
{
  "answer": "The refund policy says...",
  "speak": "The site says refunds are available...",
  "citations": [
    {
      "title": "Refund Policy",
      "url": "https://example.com/refund"
    }
  ],
  "confidence": 0.88
}
```

---

### Ingest website

```http
POST /websites/ingest
```

Input:

```json
{
  "root_url": "https://example.com",
  "crawl_depth": 3,
  "max_pages": 500
}
```

---

### Search website

```http
POST /websites/:website_id/search
```

Input:

```json
{
  "query": "refund policy",
  "top_k": 8
}
```

---

### SQL/API tools

```http
POST /tools/get-order-status
POST /tools/search-customers
POST /tools/get-invoice-summary
```

Keep these as normal backend endpoints so LangGraph, voice, and future agents can all use them.

---

## 9. Toolset for Agent One

### Website tools

```text
search_website(query, website_id, top_k)
get_page(url)
list_website_pages(website_id)
refresh_website_crawl(website_id)
```

### SQL/API tools

```text
get_customer(identifier)
get_order_status(order_id)
get_invoice_summary(customer_id)
search_records(entity, filters)
run_readonly_sql(query)
```

### Utility tools

```text
ask_clarification(question)
handoff_to_human(reason)
create_ticket(summary)
```

---

## 10. MVP build sequence

### Phase 1 — Website Q&A only

Build:

```text
website crawler
chunker
pgvector storage
semantic search
LangGraph website_qa flow
text API
```

Test with:

```text
“What services do they offer?”
“What is the refund policy?”
“What are the pricing plans?”
“Where are they located?”
```

---

### Phase 2 — Add API tools

Add mock business APIs:

```text
orders
customers
appointments
invoices
```

Agent can answer:

```text
“What is my order status?”
“Do I have any unpaid invoices?”
“Can I book a slot tomorrow?”
```

---

### Phase 3 — Add SQL mode

Add:

```text
schema introspection
SQL generation
SQL validator
read-only executor
query result summarizer
```

Start with internal/dev DB only.

---

### Phase 4 — Hybrid answers

Example:

```text
User: “Does the website allow refunds, and is my refund processed?”
```

Agent does:

```text
website search → refund policy
API call → user refund status
compose combined answer
```

---

### Phase 5 — Connect to Voice Wrapper

Register Agent One:

```python
AGENT_REGISTRY["agent_one"] = AgentConfig(
    graph=agent_one_graph,
    instructions="Answer using scraped website data and approved backend tools.",
    voice_enabled=True,
)
```

Then Plan 1 can invoke Agent One through voice.

---

## 11. Folder structure

```text
agent-one/
  app/
    main.py
    routes/
      agent_one.py
      websites.py
      tools.py

    graph/
      state.py
      graph.py
      nodes/
        normalize.py
        intent_router.py
        retrieve_website.py
        sql_or_api_tool.py
        answer_composer.py
        fallback.py

    ingestion/
      crawler.py
      extractor.py
      chunker.py
      embedder.py
      indexer.py

    retrieval/
      hybrid_search.py
      reranker.py

    tools/
      website_tools.py
      api_tools.py
      sql_tools.py

    db/
      models.py
      migrations/

    evals/
      website_qa_eval.py
      sql_eval.py
      hybrid_eval.py
```

---

# How both plans connect

Final combined architecture:

```text
User speaks
  ↓
Voice / Realtime Wrapper
  ↓
run_agent(agent_id="agent_one")
  ↓
Agent One LangGraph
  ├─ website semantic search
  ├─ SQL/API tools
  └─ answer composer
  ↓
Voice Wrapper
  ↓
Realtime spoken answer
```

But Agent One also works without voice:

```text
Chat UI / API caller
  ↓
POST /agents/agent-one/invoke
  ↓
Agent One LangGraph
  ↓
JSON answer
```

That separation is the key design win. **Voice becomes an adapter, not the agent itself.**

[1]: https://platform.openai.com/docs/guides/realtime-webrtc?utm_source=chatgpt.com "Realtime API with WebRTC | OpenAI API"
