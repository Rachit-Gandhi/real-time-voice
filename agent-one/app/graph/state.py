from typing import TypedDict


class AgentOneState(TypedDict, total=False):
    user_id: str
    thread_id: str
    user_message: str
    messages: list
    intent: str
    retrieved_chunks: list
    draft_answer: str | None
    final_answer: str | None
    speak: str | None
    citations: list
    confidence: float
