from app.graph.state import AgentOneState


def answer_composer(state: AgentOneState) -> AgentOneState:
    chunks = state.get("retrieved_chunks") or []
    api_result = state.get("api_result")
    sql_result = state.get("sql_result")

    if not chunks and not api_result and not sql_result:
        return {
            **state,
            "final_answer": "I could not find relevant information to answer your question.",
            "speak": "I could not find relevant information to answer your question.",
            "citations": [],
            "sources": [],
            "confidence": 0.0,
            "requires_followup": False,
        }

    answer_parts: list[str] = []
    speak_parts: list[str] = []

    if chunks:
        top = chunks[0]
        answer_parts.append(f"According to {top['title']}, {top['content']}")
        speak_parts.append(_voice_summary(top["content"]))

    if sql_result:
        answer_parts.append(_format_sql_answer(sql_result))
        speak_parts.append(_format_sql_speak(sql_result))
    elif api_result:
        answer_parts.append(_format_api_answer(api_result))
        speak_parts.append(_format_api_speak(api_result))

    citations = [{"title": c["title"], "url": c["url"]} for c in chunks]
    sources = [{"type": "website", **citation} for citation in citations]
    if sql_result:
        sources.append({"type": "sql", "query": (sql_result.get("sql") or "")[:200]})
    elif api_result:
        sources.append({"type": "api", "tool": api_result.get("tool")})

    confidence = 0.78
    if chunks and (sql_result or api_result):
        confidence = 0.84
    elif state.get("retrieval_score"):
        confidence = min(0.9, max(0.55, float(state["retrieval_score"])))

    return {
        **state,
        "final_answer": "\n\n".join(answer_parts),
        "speak": " ".join(part for part in speak_parts if part),
        "citations": citations,
        "sources": sources,
        "confidence": round(confidence, 2),
        "requires_followup": False,
    }


def _voice_summary(text: str) -> str:
    sentence = text.split(".")[0].strip()
    return sentence + "." if sentence else text


def _format_sql_answer(sql_result: dict) -> str:
    if "error" in sql_result:
        return f"Database query failed: {sql_result['error']}"
    rows = sql_result.get("rows") or []
    count = sql_result.get("row_count", len(rows))
    if not rows:
        return "The database query returned no results."
    lines = [f"Database returned {count} result(s):"]
    for row in rows[:5]:
        lines.append("  " + ", ".join(f"{k}: {v}" for k, v in row.items()))
    return "\n".join(lines)


def _format_sql_speak(sql_result: dict) -> str:
    if "error" in sql_result:
        return "The database query could not be completed."
    rows = sql_result.get("rows") or []
    count = sql_result.get("row_count", len(rows))
    if not rows:
        return "The database returned no results for your question."
    return f"I found {count} result{'s' if count != 1 else ''} from the database."


def _format_api_answer(api_result: dict) -> str:
    tool = api_result.get("tool")
    data = api_result.get("data") or {}
    if tool == "get_order_status":
        return (
            f"Order {data['order_id']} is {data['status']}. "
            f"ETA: {data['eta']}. Latest note: {data['latest_note']}"
        )
    if tool == "get_invoice_summary":
        return (
            f"There are {data['open_invoice_count']} open invoices totaling "
            f"{data['currency']} {data['total_due']:.2f}. Next due date: {data['next_due_date']}."
        )
    if tool == "search_appointments":
        slots = data.get("available_slots", [])
        if not slots:
            return "No appointment slots are currently available."
        return "Available appointment slots: " + ", ".join(slot["starts_at"] for slot in slots) + "."
    if tool == "get_customer":
        return f"Customer {data['name']} is on the {data['plan']} plan."
    return "The business API returned structured data for this request."


def _format_api_speak(api_result: dict) -> str:
    tool = api_result.get("tool")
    data = api_result.get("data") or {}
    if tool == "get_order_status":
        return f"Your order is {data['status']} and is expected by {data['eta']}."
    if tool == "get_invoice_summary":
        return f"You have {data['open_invoice_count']} open invoice totaling {data['currency']} {data['total_due']:.2f}."
    if tool == "search_appointments":
        slots = data.get("available_slots", [])
        return f"I found {len(slots)} available appointment slots."
    if tool == "get_customer":
        return f"The account is on the {data['plan']} plan."
    return "I found structured account data for this request."
