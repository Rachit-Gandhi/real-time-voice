from langchain_openai import ChatOpenAI
from app.graph.state import AgentOneState

_SYSTEM = """You are a helpful assistant that answers user questions based on provided website content.

Rules:
- Use ONLY the information in the provided chunks.
- Cite the source page titles when relevant.
- If the information is not in the chunks, say you could not find it.
- Keep answers factual and concise.
- The "speak" version should be shorter and suitable for text-to-speech (no markdown, no URLs)."""


def answer_composer(state: AgentOneState) -> AgentOneState:
    chunks = state.get("retrieved_chunks") or []
    user_message = state.get("user_message", "")

    if not chunks:
        return {
            **state,
            "final_answer": "I could not find relevant information to answer your question.",
            "speak": "I could not find relevant information to answer your question.",
            "citations": [],
            "confidence": 0.0,
        }

    context = "\n\n".join(
        f"[{c['title']}] ({c['url']})\n{c['content']}" for c in chunks
    )
    prompt = (
        f"Website content:\n{context}\n\n"
        f"User question: {user_message}\n\n"
        "Respond in JSON with keys: answer (full markdown answer), speak (short voice-friendly version)."
    )

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    response = llm.invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": prompt},
    ])

    import json
    try:
        parsed = json.loads(response.content)
        final_answer = parsed.get("answer", response.content)
        speak = parsed.get("speak", final_answer)
    except (json.JSONDecodeError, AttributeError):
        final_answer = response.content
        speak = response.content

    citations = [{"title": c["title"], "url": c["url"]} for c in chunks]

    return {
        **state,
        "final_answer": final_answer,
        "speak": speak,
        "citations": citations,
        "confidence": 0.85,
    }
