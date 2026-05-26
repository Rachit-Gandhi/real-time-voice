from langgraph.graph import StateGraph, END
from app.graph.state import AgentOneState
from app.graph.nodes.normalize import normalize
from app.graph.nodes.intent_router import route_intent
from app.graph.nodes.retrieve_website import retrieve_website
from app.graph.nodes.api_tools import call_api_tool
from app.graph.nodes.answer_composer import answer_composer
from app.graph.nodes.fallback import fallback


def _route_after_intent(state: AgentOneState) -> str:
    intent = state.get("intent", "unsupported")
    if intent in ("website_qa", "hybrid"):
        return "retrieve_website"
    if intent == "sql_qa":
        return "api_tools"
    return "fallback"


def _route_after_retrieval(state: AgentOneState) -> str:
    if state.get("intent") == "hybrid":
        return "api_tools"
    return "answer_composer"


def build_graph():
    g = StateGraph(AgentOneState)
    g.add_node("normalize", normalize)
    g.add_node("intent_router", route_intent)
    g.add_node("retrieve_website", retrieve_website)
    g.add_node("api_tools", call_api_tool)
    g.add_node("answer_composer", answer_composer)
    g.add_node("fallback", fallback)

    g.set_entry_point("normalize")
    g.add_edge("normalize", "intent_router")
    g.add_conditional_edges("intent_router", _route_after_intent, {
        "retrieve_website": "retrieve_website",
        "api_tools": "api_tools",
        "fallback": "fallback",
    })
    g.add_conditional_edges("retrieve_website", _route_after_retrieval, {
        "api_tools": "api_tools",
        "answer_composer": "answer_composer",
    })
    g.add_edge("api_tools", "answer_composer")
    g.add_edge("answer_composer", END)
    g.add_edge("fallback", END)

    return g.compile()
