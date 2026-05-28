import os

from langchain_openai import ChatOpenAI
from app.graph.state import AgentOneState

_SYSTEM = """You are an intent classifier. Given a user message, classify it into exactly one of these categories:
- website_qa: questions about website content, company info, policies, FAQs, etc.
- sql_qa: questions about data in the database — inventory, stock levels, item quantities, prices, orders, customers, etc.
- hybrid: questions that require both website content and database data
- clarification: ambiguous questions that need more context
- unsupported: off-topic questions unrelated to the business

Reply with ONLY the category name, nothing else."""

# Module-level handle; patched in tests via patch("app.graph.nodes.intent_router._llm").
# Lazily instantiated so importing this module never raises without an API key.
_llm: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    global _llm
    if _llm is None:
        from app import config
        _llm = ChatOpenAI(model=config.OPENAI_MODEL, temperature=0)
    return _llm


def route_intent(state: AgentOneState) -> AgentOneState:
    intent = classify_intent(state.get("user_message", ""))
    if intent:
        return {**state, "intent": intent}

    if not os.getenv("OPENAI_API_KEY"):
        return {**state, "intent": "sql_qa" if os.getenv("DATABASE_URL") else "website_qa"}

    llm = _get_llm()
    message = state.get("user_message", "")
    response = llm.invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": message},
    ])
    intent = response.content.strip().lower()
    return {**state, "intent": intent}


def classify_intent(message: str) -> str | None:
    text = message.lower()
    sql_terms = (
        "order",
        "orders",
        "customer",
        "account",
        "invoice",
        "how many",
        "how much",
        "stock",
        "in stock",
        "quantity",
        "inventory",
        "item",
        "items",
        "price of",
        "cost of",
        "available",
        "low stock",
        "out of stock",
        "total",
        "list all",
        "show me",
        "appointment",
        "booking",
        "slot",
    )
    website_terms = (
        "policy",
        "about us",
        "contact",
        "website",
        "site",
        "page",
        "faq",
        "help",
        "hours",
        "location",
        "return",
        "not working",
        "broken",
        "down",
        "issue",
        "problem",
        "error",
        "support",
    )
    unsupported_terms = ("weather", "sports", "joke", "recipe", "movie")

    has_sql = any(term in text for term in sql_terms)
    has_website = any(term in text for term in website_terms)

    if has_sql and has_website:
        return "hybrid"
    if has_sql:
        return "sql_qa"
    if has_website:
        return "website_qa"
    if any(term in text for term in unsupported_terms):
        return "unsupported"
    if len(text.split()) <= 2:
        return "clarification"
    return None
