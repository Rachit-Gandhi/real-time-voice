from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

DEFAULT_WEBSITE_ID = "demo-site"
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "do",
    "does",
    "i",
    "is",
    "me",
    "my",
    "of",
    "the",
    "to",
    "what",
    "you",
    "your",
}


@dataclass(frozen=True)
class WebsiteDocument:
    url: str
    title: str
    content: str
    website_id: str = DEFAULT_WEBSITE_ID


@dataclass(frozen=True)
class WebsiteChunk:
    chunk_id: str
    website_id: str
    url: str
    title: str
    content: str
    score: float = 0.0

    def as_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "website_id": self.website_id,
            "url": self.url,
            "title": self.title,
            "content": self.content,
            "score": self.score,
        }


class TextChunker:
    def __init__(self, max_words: int = 90, overlap_words: int = 15) -> None:
        self.max_words = max_words
        self.overlap_words = overlap_words

    def chunk(self, document: WebsiteDocument) -> list[WebsiteChunk]:
        words = document.content.split()
        if not words:
            return []

        chunks = []
        step = max(1, self.max_words - self.overlap_words)
        for index, start in enumerate(range(0, len(words), step)):
            text = " ".join(words[start : start + self.max_words]).strip()
            if not text:
                continue
            chunk_id = stable_chunk_id(document.website_id, document.url, index)
            chunks.append(
                WebsiteChunk(
                    chunk_id=chunk_id,
                    website_id=document.website_id,
                    url=document.url,
                    title=document.title,
                    content=text,
                )
            )
        return chunks


class HashingEmbedder:
    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions
        self.model_id = f"hash-{dimensions}"

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        counts = Counter(tokenize(text))
        for token, count in counts.items():
            index = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % self.dimensions
            vector[index] += float(count)
        return normalize_vector(vector)


class OpenAIEmbedder:
    """OpenAI text-embedding-3-small embedder with batch support."""

    DEFAULT_MODEL = "text-embedding-3-small"

    def __init__(self, model: str = DEFAULT_MODEL) -> None:
        self.model = model
        self.model_id = f"openai-{model}"
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            import openai
            self._client = openai.OpenAI()
        return self._client

    def embed(self, text: str) -> list[float]:
        resp = self._get_client().embeddings.create(input=[text], model=self.model)
        return resp.data[0].embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for i in range(0, len(texts), 100):
            batch = texts[i : i + 100]
            resp = self._get_client().embeddings.create(input=batch, model=self.model)
            items = sorted(resp.data, key=lambda x: x.index)
            results.extend(item.embedding for item in items)
        return results


def make_embedder() -> HashingEmbedder | OpenAIEmbedder:
    """Return OpenAIEmbedder when OPENAI_API_KEY is set, else HashingEmbedder."""
    import os
    if os.getenv("OPENAI_API_KEY"):
        return OpenAIEmbedder()
    return HashingEmbedder()


class InMemoryVectorStore:
    def __init__(self, embedder: Any = None) -> None:
        self.embedder = embedder if embedder is not None else make_embedder()
        self._records: list[tuple[WebsiteChunk, list[float], set[str]]] = []

    def add_chunks(self, chunks: Iterable[WebsiteChunk]) -> None:
        chunk_list = list(chunks)
        texts = [f"{c.title} {c.content}" for c in chunk_list]
        if hasattr(self.embedder, "embed_batch"):
            embeddings = self.embedder.embed_batch(texts)
        else:
            embeddings = [self.embedder.embed(t) for t in texts]
        for chunk, emb, text in zip(chunk_list, embeddings, texts):
            self._records.append((chunk, emb, set(tokenize(text))))

    def search(self, query: str, *, website_id: str | None = None, top_k: int = 4) -> list[WebsiteChunk]:
        query_embedding = self.embedder.embed(query)
        query_tokens = set(tokenize(query))
        scored: list[WebsiteChunk] = []
        for chunk, embedding, tokens in self._records:
            if website_id and chunk.website_id != website_id:
                continue
            semantic_score = cosine_similarity(query_embedding, embedding)
            keyword_score = keyword_overlap(query_tokens, tokens)
            score = (0.25 * semantic_score) + (0.75 * keyword_score)
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


class WebsiteRetrievalPipeline:
    def __init__(
        self,
        *,
        chunker: TextChunker | None = None,
        vector_store: Any = None,
    ) -> None:
        self.chunker = chunker or TextChunker()
        self.vector_store = vector_store or InMemoryVectorStore()

    def ingest_documents(self, documents: Iterable[WebsiteDocument]) -> list[WebsiteChunk]:
        chunks: list[WebsiteChunk] = []
        for document in documents:
            chunks.extend(self.chunker.chunk(document))
        self.vector_store.add_chunks(chunks)
        return chunks

    def search(self, query: str, *, website_id: str | None = None, top_k: int = 4) -> list[WebsiteChunk]:
        return self.vector_store.search(query, website_id=website_id, top_k=top_k)


def tokenize(text: str) -> list[str]:
    return [stem_token(token) for token in _TOKEN_RE.findall(text.lower()) if len(token) > 1 and token not in _STOPWORDS]


def stem_token(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def normalize_vector(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


def keyword_overlap(query_tokens: set[str], chunk_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    return len(query_tokens & chunk_tokens) / len(query_tokens)


def stable_chunk_id(website_id: str, url: str, index: int) -> str:
    digest = hashlib.sha1(f"{website_id}:{url}:{index}".encode("utf-8")).hexdigest()[:12]
    return f"chunk_{digest}"


def default_documents() -> list[WebsiteDocument]:
    return [
        WebsiteDocument(
            url="https://example.com/services",
            title="Services",
            content=(
                "We offer consulting, custom software development, and 24/7 technical support. "
                "Our team specializes in cloud-native architectures, integration work, and "
                "AI-powered business solutions."
            ),
        ),
        WebsiteDocument(
            url="https://example.com/pricing",
            title="Pricing",
            content=(
                "The Starter plan is 49 dollars per month and supports up to 5 users with core "
                "features. The Professional plan is 149 dollars per month and supports up to 25 "
                "users with priority support. Enterprise plans use custom pricing with SLA guarantees."
            ),
        ),
        WebsiteDocument(
            url="https://example.com/refund-policy",
            title="Refund Policy",
            content=(
                "All plans include a 30-day money-back guarantee. Refunds are processed within "
                "5 to 7 business days to the original payment method after approval."
            ),
        ),
    ]
