from app.graph.state import AgentOneState
from app.retrieval import DEFAULT_WEBSITE_ID, get_default_pipeline


def retrieve_website(state: AgentOneState) -> AgentOneState:
    context = state.get("context") or {}
    website_id = state.get("website_id") or context.get("website_id") or DEFAULT_WEBSITE_ID
    chunks = get_default_pipeline().search(
        state.get("user_message", ""),
        website_id=website_id,
        top_k=int(context.get("top_k", 4)),
    )
    return {
        **state,
        "website_id": website_id,
        "retrieved_chunks": [chunk.as_dict() for chunk in chunks],
        "retrieval_score": chunks[0].score if chunks else 0.0,
    }
