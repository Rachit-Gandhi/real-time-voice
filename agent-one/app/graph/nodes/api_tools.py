from __future__ import annotations

import os

from app.graph.state import AgentOneState
from app.tools.business_api import MockBusinessApiTools, extract_order_id

_TOOLS = MockBusinessApiTools()


def call_api_tool(state: AgentOneState) -> AgentOneState:
    database_url = os.getenv("DATABASE_URL", "")
    if database_url:
        return _call_sql(state, database_url)
    return _call_mock(state)


def _call_sql(state: AgentOneState, database_url: str) -> AgentOneState:
    from app.database.sql_engine import SQLQueryEngine

    engine = SQLQueryEngine(database_url)
    result = engine.answer_question(state.get("user_message", ""))
    return {**state, "api_action": "sql_query", "sql_result": result}


def _call_mock(state: AgentOneState) -> AgentOneState:
    message = state.get("user_message", "").lower()
    context = state.get("context") or {}
    customer_id = context.get("customer_id") or state.get("user_id") or "cust_123"

    if "invoice" in message or "bill" in message or "due" in message:
        action = "get_invoice_summary"
        api_result = _TOOLS.get_invoice_summary(customer_id)
    elif "appointment" in message or "book" in message or "slot" in message:
        action = "search_appointments"
        api_result = _TOOLS.search_appointments(customer_id)
    elif "customer" in message or "account" in message or "plan" in message:
        action = "get_customer"
        api_result = _TOOLS.get_customer(customer_id)
    else:
        action = "get_order_status"
        api_result = _TOOLS.get_order_status(extract_order_id(message))

    return {**state, "api_action": action, "api_result": api_result}
