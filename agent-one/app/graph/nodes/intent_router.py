import os

from langchain_openai import ChatOpenAI
from app.graph.state import AgentOneState

_SYSTEM = """You are an intent classifier. Given a user message, classify it into exactly one of these categories:
- website_qa: questions about website content, services, policies, pricing, company info, refunds, etc.
- sql_qa: questions about specific user data, orders, account status, invoices, etc.
- hybrid: questions that require both website content and user-specific data
- clarification: ambiguous questions that need more context
- unsupported: off-topic questions unrelated to the business

Reply with ONLY the category name, nothing else."""

# Module-level handle; patched in tests via patch("app.graph.nodes.intent_router._llm").
# Lazily instantiated so importing this module never raises without an API key.
_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    return _llm


def route_intent(state: AgentOneState) -> AgentOneState:
    intent = classify_intent(state.get("user_message", ""))
    if intent:
        return {**state, "intent": intent}

    if not os.getenv("OPENAI_API_KEY"):
        return {**state, "intent": "website_qa"}

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    message = state.get("user_message", "")
    response = llm.invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": message},
    ])
    intent = response.content.strip().lower()
    return {**state, "intent": intent}


def classify_intent(message: str) -> str | None:
    text = message.lower()
    api_terms = (
        "order",
        "customer",
        "account",
        "invoice",
        "appointment",
        "booking",
        "book ",
        "slot",
        "refund status",
        "my refund",
        "my plan",
        "my subscription",
    )
    website_terms = (
        "service",
        "pricing",
        "price",
        "plan",
        "refund policy",
        "policy",
        "website",
        "offer",
        "support",
        "guarantee",
        "sla",
    )
    unsupported_terms = ("weather", "sports", "joke", "recipe", "movie")

    has_api = any(term in text for term in api_terms)
    has_website = any(term in text for term in website_terms)

    if has_api and has_website:
        return "hybrid"
    if has_api:
        return "sql_qa"
    if has_website:
        return "website_qa"
    if any(term in text for term in unsupported_terms):
        return "unsupported"
    if len(text.split()) <= 2:
        return "clarification"
    return None
