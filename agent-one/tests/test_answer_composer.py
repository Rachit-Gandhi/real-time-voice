from unittest.mock import patch, MagicMock
from app.graph.nodes.answer_composer import answer_composer

_MOCK_CHUNKS = [
    {
        "chunk_id": "c1",
        "url": "https://example.com/services",
        "title": "Services",
        "content": "We offer consulting and software development.",
    },
]


def _make_llm_response(text: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.content = text
    return mock_resp


def test_answer_composer_returns_answer_and_speak():
    json_reply = '{"answer": "We offer consulting.", "speak": "We offer consulting."}'
    with patch("app.graph.nodes.answer_composer.ChatOpenAI") as MockLLM:
        MockLLM.return_value.invoke.return_value = _make_llm_response(json_reply)
        state = {
            "user_message": "What services do you offer?",
            "thread_id": "t1",
            "retrieved_chunks": _MOCK_CHUNKS,
            "citations": [],
        }
        result = answer_composer(state)

    assert isinstance(result["final_answer"], str) and result["final_answer"]
    assert isinstance(result["speak"], str) and result["speak"]
    assert isinstance(result["citations"], list)
    assert result["citations"][0]["url"] == "https://example.com/services"


def test_answer_composer_handles_non_json_response():
    plain_reply = "We offer consulting and software development."
    with patch("app.graph.nodes.answer_composer.ChatOpenAI") as MockLLM:
        MockLLM.return_value.invoke.return_value = _make_llm_response(plain_reply)
        state = {
            "user_message": "What services?",
            "thread_id": "t2",
            "retrieved_chunks": _MOCK_CHUNKS,
            "citations": [],
        }
        result = answer_composer(state)

    assert result["final_answer"] == plain_reply
    assert result["speak"] == plain_reply


def test_answer_composer_no_chunks_returns_fallback():
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
