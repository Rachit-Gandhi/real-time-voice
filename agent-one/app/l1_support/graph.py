from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.l1_support.state import L1SupportState
from app.l1_support.nodes.triage import triage
from app.l1_support.nodes.file_ticket import file_ticket


def _route_after_triage(state: L1SupportState) -> str:
    if state.get("stage") == "filing":
        return "file_ticket"
    return END


_checkpointer = MemorySaver()


def build_l1_graph():
    g = StateGraph(L1SupportState)
    g.add_node("triage", triage)
    g.add_node("file_ticket", file_ticket)

    g.set_entry_point("triage")
    g.add_conditional_edges("triage", _route_after_triage, {
        "file_ticket": "file_ticket",
        END: END,
    })
    g.add_edge("file_ticket", END)

    return g.compile(checkpointer=_checkpointer)
