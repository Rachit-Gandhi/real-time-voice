from app.graph.nodes.retrieve_website import retrieve_website
from app.retrieval.pipeline import WebsiteDocument, WebsiteRetrievalPipeline


def test_retrieve_website_returns_chunks():
    state = {
        "user_message": "What services do you offer?",
        "thread_id": "t1",
        "messages": [],
        "retrieved_chunks": [],
        "citations": [],
    }
    result = retrieve_website(state)
    chunks = result["retrieved_chunks"]
    assert isinstance(chunks, list)
    assert len(chunks) >= 1
    assert chunks[0]["title"] == "Services"
    for chunk in chunks:
        assert "chunk_id" in chunk
        assert "url" in chunk
        assert "title" in chunk
        assert "content" in chunk
        assert "score" in chunk
        assert isinstance(chunk["content"], str) and chunk["content"]


def test_retrieve_website_preserves_state():
    state = {
        "user_message": "test",
        "thread_id": "t2",
        "messages": [],
        "retrieved_chunks": [],
        "citations": [],
        "intent": "website_qa",
    }
    result = retrieve_website(state)
    assert result["user_message"] == "test"
    assert result["intent"] == "website_qa"


def test_retrieval_pipeline_ingests_and_searches_documents():
    pipeline = WebsiteRetrievalPipeline()
    pipeline.ingest_documents(
        [
            WebsiteDocument(
                website_id="local",
                url="https://local.test/refunds",
                title="Refunds",
                content="Refund approvals are completed within three business days.",
            ),
            WebsiteDocument(
                website_id="local",
                url="https://local.test/shipping",
                title="Shipping",
                content="Shipping usually takes five business days.",
            ),
        ]
    )

    results = pipeline.search("refund approval timeline", website_id="local", top_k=1)

    assert len(results) == 1
    assert results[0].title == "Refunds"
