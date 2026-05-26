from langgraph.graph import StateGraph, END
from app.graph.state import AgentOneState
from app.graph.nodes.normalize import normalize
from app.graph.nodes.intent_router import route_intent
from app.graph.nodes.fallback import fallback


def _route_after_intent(state: AgentOneState) -> str:
    intent = state.get("intent", "unsupported")
    if intent in ("website_qa", "hybrid"):
        return "fallback"
    elif intent == "sql_qa":
        return "fallback"
    else:
        return "fallback"


def build_graph():
    g = StateGraph(AgentOneState)
    g.add_node("normalize", normalize)
    g.add_node("intent_router", route_intent)
    g.add_node("fallback", fallback)

    g.set_entry_point("normalize")
    g.add_edge("normalize", "intent_router")
    g.add_conditional_edges("intent_router", _route_after_intent, {
        "fallback": "fallback",
    })
    g.add_edge("fallback", END)

    return g.compile()
