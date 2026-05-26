"""
Cycle 2: Intent router classifies website_qa, sql_qa, and unsupported.

The LLM is patched so tests are hermetic and do not require an API key.
"""
import pytest
from unittest.mock import patch, MagicMock
from app.graph.nodes.intent_router import route_intent


def _make_llm_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    return msg


@pytest.mark.integration
def test_intent_router_classifies_website_qa():
    state = {
        "user_message": "What is the refund policy?",
        "thread_id": "t-cycle2-1",
        "messages": [],
        "retrieved_chunks": [],
        "citations": [],
    }
    with patch("app.graph.nodes.intent_router._llm") as mock_llm:
        mock_llm.invoke.return_value = _make_llm_response("website_qa")
        result = route_intent(state)
    assert result["intent"] == "website_qa"


@pytest.mark.integration
def test_intent_router_classifies_sql_qa():
    state = {
        "user_message": "What is my current order status?",
        "thread_id": "t-cycle2-2",
        "messages": [],
        "retrieved_chunks": [],
        "citations": [],
    }
    with patch("app.graph.nodes.intent_router._llm") as mock_llm:
        mock_llm.invoke.return_value = _make_llm_response("sql_qa")
        result = route_intent(state)
    assert result["intent"] == "sql_qa"


@pytest.mark.integration
def test_intent_router_classifies_unsupported():
    state = {
        "user_message": "What is the capital of France?",
        "thread_id": "t-cycle2-3",
        "messages": [],
        "retrieved_chunks": [],
        "citations": [],
    }
    with patch("app.graph.nodes.intent_router._llm") as mock_llm:
        mock_llm.invoke.return_value = _make_llm_response("unsupported")
        result = route_intent(state)
    assert result["intent"] == "unsupported"
