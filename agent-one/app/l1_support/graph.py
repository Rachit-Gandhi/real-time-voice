from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.l1_support.state import L1SupportState
from app.l1_support.nodes.faq_search import faq_search
from app.l1_support.nodes.collect_details import collect_details
from app.l1_support.nodes.create_ticket import create_ticket
from app.l1_support.nodes.escalate import escalate
from app.l1_support.nodes.compose import compose_answer


def _route_initial(state: L1SupportState) -> str:
    stage = state.get("stage", "start")
    if stage == "collecting":
        return "collect_details"
    if stage == "ticket_created":
        return "compose_answer"
    return "faq_search"


def _route_after_faq(state: L1SupportState) -> str:
    if state.get("faq_matched"):
        return "compose_answer"
    return "collect_details"


def _route_after_collect(state: L1SupportState) -> str:
    if state.get("requires_more_info"):
        return "compose_answer"
    return "create_ticket"


def _entry_router(state: L1SupportState) -> L1SupportState:
    return state


_checkpointer = MemorySaver()


def build_l1_graph():
    g = StateGraph(L1SupportState)
    g.add_node("entry_router", _entry_router)
    g.add_node("faq_search", faq_search)
    g.add_node("collect_details", collect_details)
    g.add_node("create_ticket", create_ticket)
    g.add_node("escalate", escalate)
    g.add_node("compose_answer", compose_answer)

    g.set_entry_point("entry_router")
    g.add_conditional_edges("entry_router", _route_initial, {
        "faq_search": "faq_search",
        "collect_details": "collect_details",
        "compose_answer": "compose_answer",
    })
    g.add_conditional_edges("faq_search", _route_after_faq, {
        "compose_answer": "compose_answer",
        "collect_details": "collect_details",
    })
    g.add_conditional_edges("collect_details", _route_after_collect, {
        "compose_answer": "compose_answer",
        "create_ticket": "create_ticket",
    })
    g.add_edge("create_ticket", "escalate")
    g.add_edge("escalate", "compose_answer")
    g.add_edge("compose_answer", END)
    return g.compile(checkpointer=_checkpointer)
