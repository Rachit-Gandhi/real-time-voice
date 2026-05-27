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


def test_api_intent_routes_to_tool_result():
    graph = build_graph()
    state = graph.invoke(
        {
            "user_message": "What is my order status?",
            "thread_id": "test-routing-2",
            "messages": [],
            "retrieved_chunks": [],
            "citations": [],
        }
    )
    assert state["intent"] == "sql_qa"
    assert state["api_result"]["tool"] == "get_order_status"
    assert "order" in state["final_answer"].lower()


def test_hybrid_intent_uses_retrieval_and_api_tool():
    graph = build_graph()
    state = graph.invoke(
        {
            "user_message": "What is the refund policy and my order status?",
            "thread_id": "test-routing-3",
            "messages": [],
            "retrieved_chunks": [],
            "citations": [],
        }
    )
    assert state["intent"] == "hybrid"
    assert isinstance(state["retrieved_chunks"], list)
    assert state["api_result"]["tool"] == "get_order_status"
