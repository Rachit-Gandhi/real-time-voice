from app.graph.nodes.answer_composer import answer_composer

_MOCK_CHUNKS = [
    {
        "chunk_id": "c1",
        "url": "https://example.com/services",
        "title": "Services",
        "content": "We offer consulting and software development.",
        "score": 0.8,
    },
]


def test_answer_composer_returns_answer_and_speak_from_chunks():
    state = {
        "user_message": "What services do you offer?",
        "thread_id": "t1",
        "retrieved_chunks": _MOCK_CHUNKS,
        "citations": [],
        "retrieval_score": 0.8,
    }
    result = answer_composer(state)

    assert "consulting" in result["final_answer"].lower()
    assert isinstance(result["speak"], str) and result["speak"]
    assert isinstance(result["citations"], list)
    assert result["citations"][0]["url"] == "https://example.com/services"
    assert result["sources"][0]["type"] == "website"


def test_answer_composer_combines_api_and_website_data():
    state = {
        "user_message": "What is the refund policy and my order status?",
        "thread_id": "t2",
        "retrieved_chunks": _MOCK_CHUNKS,
        "api_result": {
            "tool": "get_order_status",
            "data": {
                "order_id": "ord_1001",
                "status": "in transit",
                "eta": "2026-05-29",
                "latest_note": "Package left the regional facility.",
            },
        },
        "citations": [],
    }
    result = answer_composer(state)

    assert "consulting" in result["final_answer"].lower()
    assert "ord_1001" in result["final_answer"]
    assert result["sources"][-1] == {"type": "api", "tool": "get_order_status"}


def test_answer_composer_no_data_returns_fallback():
    state = {
        "user_message": "What services?",
        "thread_id": "t3",
        "retrieved_chunks": [],
        "citations": [],
    }
    result = answer_composer(state)
    assert "could not find" in result["final_answer"].lower()
    assert result["confidence"] == 0.0
    assert result["citations"] == []
