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


@pytest.mark.integration
def test_sql_qa_intent():
    graph = build_graph()
    state = graph.invoke(
        {
            "user_message": "What is my order status for order 1234?",
            "thread_id": "test-routing-2",
            "messages": [],
            "retrieved_chunks": [],
            "citations": [],
        }
    )
    assert state["intent"] == "sql_qa"


@pytest.mark.integration
def test_unsupported_intent():
    graph = build_graph()
    state = graph.invoke(
        {
            "user_message": "Tell me a random joke",
            "thread_id": "test-routing-3",
            "messages": [],
            "retrieved_chunks": [],
            "citations": [],
        }
    )
    assert state["intent"] == "unsupported"
