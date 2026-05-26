import pytest
from app.graph.graph import build_graph


@pytest.mark.integration
def test_website_qa_intent():
    graph = build_graph()
    state = graph.invoke(
        {
            "user_message": "What is the refund policy?",
            "thread_id": "test-routing-1",
            "messages": [],
            "retrieved_chunks": [],
            "citations": [],
        }
    )
    assert state["intent"] == "website_qa"
