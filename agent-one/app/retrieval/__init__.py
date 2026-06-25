from __future__ import annotations

import os

from app.retrieval.pipeline import (
    DEFAULT_WEBSITE_ID,
    HashingEmbedder,
    InMemoryVectorStore,
    OpenAIEmbedder,
    TextChunker,
    WebsiteChunk,
    WebsiteDocument,
    WebsiteRetrievalPipeline,
    default_documents,
    make_embedder,
)

__all__ = [
    "DEFAULT_WEBSITE_ID",
    "HashingEmbedder",
    "InMemoryVectorStore",
    "OpenAIEmbedder",
    "TextChunker",
    "WebsiteChunk",
    "WebsiteDocument",
    "WebsiteRetrievalPipeline",
    "default_documents",
    "get_default_pipeline",
    "make_embedder",
    "reset_default_pipeline",
]

_default_pipeline: WebsiteRetrievalPipeline | None = None


def get_default_pipeline() -> WebsiteRetrievalPipeline:
    global _default_pipeline
    if _default_pipeline is not None:
        return _default_pipeline

    index_db_path = os.getenv("INDEX_DB_PATH", "agent_one_index.db")

    if index_db_path:
        from app.retrieval.store import SQLiteVectorStore

        store = SQLiteVectorStore(db_path=index_db_path)
        _default_pipeline = WebsiteRetrievalPipeline(vector_store=store)
        if store.chunk_count == 0:
            _default_pipeline.ingest_documents(default_documents())
    else:
        _default_pipeline = WebsiteRetrievalPipeline()
        _default_pipeline.ingest_documents(default_documents())

    return _default_pipeline


def reset_default_pipeline() -> None:
    """Reset the cached singleton. Use in tests to ensure isolation."""
    global _default_pipeline
    _default_pipeline = None
