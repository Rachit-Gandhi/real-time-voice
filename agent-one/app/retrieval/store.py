from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from app.retrieval.pipeline import (
    WebsiteChunk,
    cosine_similarity,
    keyword_overlap,
    tokenize,
)

logger = logging.getLogger(__name__)


class SQLiteVectorStore:
    """File-backed vector store: persists to SQLite, loads embeddings into memory for search.

    Tracks which embedder model was used. If the model changes between runs the index is
    cleared automatically so dimension mismatches never silently corrupt search results.
    """

    def __init__(self, db_path: str | Path, embedder: Any = None) -> None:
        self.db_path = str(db_path)
        if embedder is None:
            from app.retrieval.pipeline import make_embedder
            embedder = make_embedder()
        self.embedder = embedder
        self._records: list[tuple[WebsiteChunk, list[float], set[str]]] = []
        self._init_db()
        self._sync_embedder_model()
        self._load()

    # ------------------------------------------------------------------
    # DB setup
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    website_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    tokens TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def _get_meta(self, key: str) -> str:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return row[0] if row else ""

    def _set_meta(self, key: str, value: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    def _sync_embedder_model(self) -> None:
        current = getattr(self.embedder, "model_id", type(self.embedder).__name__)
        stored = self._get_meta("embedder_model")
        if stored and stored != current:
            logger.warning(
                "Embedder model changed from %r to %r — clearing index. Re-run ingestion.",
                stored,
                current,
            )
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM chunks")
        self._set_meta("embedder_model", current)

    # ------------------------------------------------------------------
    # Load / write
    # ------------------------------------------------------------------

    def _load(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT chunk_id, website_id, url, title, content, embedding, tokens FROM chunks"
            ).fetchall()
        for row in rows:
            chunk = WebsiteChunk(
                chunk_id=row[0],
                website_id=row[1],
                url=row[2],
                title=row[3],
                content=row[4],
            )
            embedding: list[float] = json.loads(row[5])
            tokens: set[str] = set(json.loads(row[6]))
            self._records.append((chunk, embedding, tokens))

    def add_chunks(self, chunks: Iterable[WebsiteChunk]) -> None:
        existing_ids = {c.chunk_id for c, _, _ in self._records}
        chunk_list = [c for c in chunks if c.chunk_id not in existing_ids]
        if not chunk_list:
            return

        texts = [f"{c.title} {c.content}" for c in chunk_list]
        if hasattr(self.embedder, "embed_batch"):
            embeddings = self.embedder.embed_batch(texts)
        else:
            embeddings = [self.embedder.embed(t) for t in texts]

        with sqlite3.connect(self.db_path) as conn:
            for chunk, embedding, text in zip(chunk_list, embeddings, texts):
                tok_list = list(tokenize(text))
                conn.execute(
                    "INSERT OR REPLACE INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        chunk.chunk_id,
                        chunk.website_id,
                        chunk.url,
                        chunk.title,
                        chunk.content,
                        json.dumps(embedding),
                        json.dumps(tok_list),
                    ),
                )
                self._records.append((chunk, embedding, set(tok_list)))
                existing_ids.add(chunk.chunk_id)

    def clear_website(self, website_id: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM chunks WHERE website_id = ?", (website_id,))
        self._records = [(c, e, t) for c, e, t in self._records if c.website_id != website_id]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self, query: str, *, website_id: str | None = None, top_k: int = 4
    ) -> list[WebsiteChunk]:
        q_emb = self.embedder.embed(query)
        q_tok = set(tokenize(query))
        scored: list[WebsiteChunk] = []
        for chunk, emb, tok in self._records:
            if website_id and chunk.website_id != website_id:
                continue
            score = 0.25 * cosine_similarity(q_emb, emb) + 0.75 * keyword_overlap(q_tok, tok)
            if score <= 0:
                continue
            scored.append(
                WebsiteChunk(
                    chunk_id=chunk.chunk_id,
                    website_id=chunk.website_id,
                    url=chunk.url,
                    title=chunk.title,
                    content=chunk.content,
                    score=round(score, 4),
                )
            )
        return sorted(scored, key=lambda c: c.score, reverse=True)[:top_k]

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def chunk_count(self) -> int:
        return len(self._records)

    def has_website(self, website_id: str) -> bool:
        return any(c.website_id == website_id for c, _, _ in self._records)
