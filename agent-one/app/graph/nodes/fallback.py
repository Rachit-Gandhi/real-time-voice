from app.graph.state import AgentOneState


def fallback(state: AgentOneState) -> AgentOneState:
    return {
        **state,
        "final_answer": "I'm sorry, I can only answer questions about this website or account data.",
        "speak": "I'm sorry, I can only answer questions about this website or account data.",
        "citations": [],
        "sources": [],
        "confidence": 0.0,
        "requires_followup": state.get("intent") == "clarification",
    }
