from app.graph.nodes.retrieve_website import retrieve_website


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
    for chunk in chunks:
        assert "chunk_id" in chunk
        assert "url" in chunk
        assert "title" in chunk
        assert "content" in chunk
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
