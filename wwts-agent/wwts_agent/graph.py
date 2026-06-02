from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from wwts_agent.state import WWTSState
from wwts_agent.nodes.converse import converse
from wwts_agent.nodes.execute import execute

_EXECUTING_STAGES = {"executing_list", "executing_get", "executing_create"}


def _route_after_converse(state: WWTSState) -> str:
    if state.get("stage") in _EXECUTING_STAGES:
        return "execute"
    return END


_checkpointer = MemorySaver()


def build_wwts_graph():
    g = StateGraph(WWTSState)
    g.add_node("converse", converse)
    g.add_node("execute", execute)

    g.set_entry_point("converse")
    g.add_conditional_edges(
        "converse",
        _route_after_converse,
        {"execute": "execute", END: END},
    )
    g.add_edge("execute", END)

    return g.compile(checkpointer=_checkpointer)
