from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.graph.graph import build_graph
from app.retrieval import DEFAULT_WEBSITE_ID

router = APIRouter()
_graph = build_graph()


class InvokeRequest(BaseModel):
    message: str
    thread_id: str
    user_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class IngestRequest(BaseModel):
    start_url: str | None = None
    max_pages: int | None = None
    website_id: str = DEFAULT_WEBSITE_ID


@router.post("/agents/agent-one/invoke")
def invoke(request: InvokeRequest):
    state = _graph.invoke({
        "user_message": request.message,
        "thread_id": request.thread_id,
        "user_id": request.user_id or "cust_123",
        "context": request.context,
        "messages": [],
        "retrieved_chunks": [],
        "citations": [],
    })
    return {
        "answer": state.get("final_answer") or "",
        "speak": state.get("speak") or "",
        "confidence": state.get("confidence", 0.0),
        "citations": state.get("citations", []),
        "sources": state.get("sources", state.get("citations", [])),
        "intent": state.get("intent"),
        "state_patch": {"last_intent": state.get("intent")},
        "requires_followup": state.get("requires_followup", False),
    }


@router.post("/agents/agent-one/ingest")
def ingest(request: IngestRequest | None = None):
    req = request or IngestRequest()
    start_url = req.start_url or os.getenv("WEBSITE_START_URL", "")
    if not start_url:
        raise HTTPException(
            status_code=422,
            detail="start_url is required (or set WEBSITE_START_URL in .env)",
        )

    max_pages = req.max_pages or int(os.getenv("WEBSITE_MAX_PAGES", "10"))
    allowed_domain = os.getenv("WEBSITE_ALLOWED_DOMAIN", "") or None
    website_id = req.website_id

    from app.retrieval.crawler import WebCrawler
    from app.retrieval import get_default_pipeline, reset_default_pipeline

    pipeline = get_default_pipeline()
    store = pipeline.vector_store

    if hasattr(store, "clear_website"):
        store.clear_website(website_id)

    crawler = WebCrawler(
        start_url,
        max_pages=max_pages,
        allowed_domain=allowed_domain,
        website_id=website_id,
    )
    documents = crawler.crawl()
    if not documents:
        return {"status": "ok", "pages_crawled": 0, "chunks_indexed": 0, "website_id": website_id}

    chunks = pipeline.ingest_documents(documents)

    # Reset singleton so next retrieve rebuilds from fresh store state
    reset_default_pipeline()

    return {
        "status": "ok",
        "pages_crawled": len(documents),
        "chunks_indexed": len(chunks),
        "website_id": website_id,
    }
