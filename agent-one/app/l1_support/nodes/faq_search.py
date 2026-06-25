import json
from pathlib import Path

from app.l1_support.state import L1SupportState

_FAQ_PATH = Path(__file__).parent.parent / "data" / "faq.json"


def _load_faq() -> list[dict]:
    with open(_FAQ_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("entries", [])


def _keyword_match(user_message: str, entries: list[dict]) -> dict | None:
    """Fallback keyword-based FAQ matching."""
    lower_msg = user_message.lower()
    best_entry = None
    best_score = 0
    for entry in entries:
        score = sum(1 for kw in entry.get("keywords", []) if kw.lower() in lower_msg)
        if score > best_score:
            best_score = score
            best_entry = entry
    if best_score >= 1:
        return best_entry
    return None


def _llm_match(user_message: str, entries: list[dict]) -> dict | None:
    """Use LLM to find the best matching FAQ entry."""
    import os
    if not os.getenv("OPENAI_API_KEY"):
        return None

    from langchain_openai import ChatOpenAI
    from app import config as cfg

    llm = ChatOpenAI(model=cfg.OPENAI_MODEL, temperature=0.0)

    faq_list = "\n".join(
        f"{e['id']}: {e['question']}" for e in entries
    )
    prompt = (
        f"User question: \"{user_message}\"\n\n"
        f"FAQ entries:\n{faq_list}\n\n"
        "If the user's question matches one of the FAQ entries with confidence above 70%, "
        "respond with ONLY the FAQ id (e.g. faq_001). "
        "If no entry matches well enough, respond with exactly: NO_MATCH"
    )
    response = llm.invoke([{"role": "user", "content": prompt}])
    result = response.content.strip()

    if result == "NO_MATCH":
        return None

    # Find the entry with the returned ID
    matched_id = result.strip().lower()
    for entry in entries:
        if entry["id"].lower() == matched_id:
            return entry

    return None


def faq_search(state: L1SupportState) -> L1SupportState:
    user_message = state.get("user_message", "")
    entries = _load_faq()

    import os
    if os.getenv("OPENAI_API_KEY"):
        matched = _llm_match(user_message, entries)
    else:
        matched = _keyword_match(user_message, entries)

    if matched:
        return {
            **state,
            "faq_matched": True,
            "faq_answer": matched["answer"],
            "faq_category": matched.get("category"),
        }

    return {
        **state,
        "faq_matched": False,
        "faq_answer": None,
        "faq_category": None,
    }
