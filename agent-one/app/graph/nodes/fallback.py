from app.graph.state import AgentOneState

_CLARIFICATION_ANSWER = (
    "I can help you with questions about this website or your account — "
    "things like policies, product info, orders, or billing. What would you like to know?"
)
_UNSUPPORTED_ANSWER = (
    "I'm sorry, I can only answer questions about this website or account data."
)


def fallback(state: AgentOneState) -> AgentOneState:
    intent = state.get("intent")
    if intent == "clarification":
        answer = _CLARIFICATION_ANSWER
    else:
        answer = _UNSUPPORTED_ANSWER
    return {
        **state,
        "final_answer": answer,
        "speak": answer,
        "citations": [],
        "sources": [],
        "confidence": 0.0,
        "requires_followup": intent == "clarification",
    }
