import re

from app.l1_support.state import L1SupportState

_REQUIRED_FIELDS = ["name", "email", "issue"]


def _extract_email(text: str) -> str | None:
    match = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    return match.group(0) if match else None


def _llm_extract(user_message: str, already_collected: dict) -> dict:
    """Use LLM to extract name, email, issue, and urgency from user_message."""
    import os
    if not os.getenv("OPENAI_API_KEY"):
        return _simple_extract(user_message, already_collected)

    from langchain_openai import ChatOpenAI
    from app import config as cfg
    import json as _json

    llm = ChatOpenAI(model=cfg.OPENAI_MODEL, temperature=0.0)

    already_str = _json.dumps(already_collected)
    prompt = (
        f"Already collected info: {already_str}\n"
        f"User message: \"{user_message}\"\n\n"
        "Extract any of the following fields from the user message that are not yet collected: "
        "name (full name), email (email address), issue (description of their problem), urgency (low/medium/high).\n"
        "Return a JSON object with only the fields you can confidently extract. "
        "Example: {\"name\": \"John Smith\", \"email\": \"john@example.com\"}\n"
        "If nothing new can be extracted, return: {}"
    )
    response = llm.invoke([{"role": "user", "content": prompt}])
    text = response.content.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)

    try:
        extracted = _json.loads(text)
        if not isinstance(extracted, dict):
            extracted = {}
    except Exception:
        extracted = {}

    return extracted


def _simple_extract(user_message: str, already_collected: dict) -> dict:
    """Fallback extraction without LLM."""
    extracted: dict = {}

    # Try to find an email if not already collected
    if "email" not in already_collected:
        email = _extract_email(user_message)
        if email:
            extracted["email"] = email

    # If we have no name yet and message is short and looks like just a name
    if "name" not in already_collected:
        words = user_message.strip().split()
        if 1 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
            extracted["name"] = user_message.strip()

    # If we have no issue yet and message is long enough
    if "issue" not in already_collected and len(user_message.strip()) > 15:
        extracted["issue"] = user_message.strip()

    return extracted


def collect_details(state: L1SupportState) -> L1SupportState:
    user_message = state.get("user_message", "")
    collected = dict(state.get("collected") or {})

    import os
    if os.getenv("OPENAI_API_KEY"):
        new_info = _llm_extract(user_message, collected)
    else:
        new_info = _simple_extract(user_message, collected)

    # Merge new info into collected
    for key, value in new_info.items():
        if value and key not in collected:
            collected[key] = value

    missing_fields = [f for f in _REQUIRED_FIELDS if not collected.get(f)]
    requires_more_info = len(missing_fields) > 0

    return {
        **state,
        "collected": collected,
        "missing_fields": missing_fields,
        "requires_more_info": requires_more_info,
        "stage": "collecting" if requires_more_info else state.get("stage", "start"),
    }
