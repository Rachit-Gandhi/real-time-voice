from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from wwts_agent.state import WWTSState
from wwts_agent.nodes.converse import converse
from wwts_agent.nodes.execute import execute

_EXECUTING_STAGES = {
    "executing_list",
    "executing_get",
    "executing_get_parts",
    "executing_get_part_line",
    "executing_get_labor",
    "executing_get_labor_activities",
    "executing_get_site",
    "executing_create",
    "executing_close",
    "executing_reopen",
    "executing_remark",
}


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
