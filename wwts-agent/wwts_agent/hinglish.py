"""Optional Hinglish rendering of agent replies.

When the caller enables the Hinglish toggle, the front end passes
``context.hinglish = true``. We translate the final reply into natural Hinglish
(Hindi-English mix in Roman/Latin script) at the invoke boundary so BOTH the
voice and chat paths get it uniformly. Codes, IDs, numbers and product
references are preserved verbatim. Falls back to the original text when there is
no API key or on any error.
"""
from __future__ import annotations

import os

_SYSTEM = (
    "You convert a customer-support reply into natural Hinglish — the casual "
    "Hindi-English mix Indians speak, written in Roman/Latin script (NOT "
    "Devanagari). Keep it warm, concise, and faithful to the original meaning.\n"
    "STRICT RULES:\n"
    "- Do NOT change or translate: work order numbers, product references, "
    "customer codes, IDs, phone numbers, emails, addresses, or any digits.\n"
    "- Keep English technical terms (work order, product reference, troubleshoot, "
    "site ID, etc.) as-is where they read naturally.\n"
    "- Preserve any list/step structure, line breaks, and the yes/no question at "
    "the end if present.\n"
    "- Return ONLY the converted text, no quotes or commentary."
)


def to_hinglish(text: str) -> str:
    text = (text or "").strip()
    if not text or not os.getenv("OPENAI_API_KEY"):
        return text
    try:
        from langchain_openai import ChatOpenAI

        model = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
        llm = ChatOpenAI(model=model, temperature=0.2)
        res = llm.invoke(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": text},
            ]
        )
        out = (res.content or "").strip()
        return out or text
    except Exception:
        return text
