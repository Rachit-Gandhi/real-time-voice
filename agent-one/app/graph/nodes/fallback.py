from app.graph.state import AgentOneState


def fallback(state: AgentOneState) -> AgentOneState:
    return {
        **state,
        "final_answer": "I'm sorry, I can only answer questions about this website or account data.",
        "speak": "I'm sorry, I can only answer questions about this website or account data.",
        "citations": [],
    }
