from typing import TypedDict


class AgentOneState(TypedDict, total=False):
    user_id: str
    thread_id: str
    user_message: str
    messages: list
    intent: str
    website_id: str | None
    retrieved_chunks: list
    sql_result: list | None
    api_result: dict | None
    draft_answer: str | None
    final_answer: str | None
    speak: str | None
    citations: list
    confidence: float
