"""Laptop troubleshooting FAQ loader + keyword matcher.

Deliberately tiny and dependency-free: the troubleshooting flow is restricted to
the two hardcoded laptop FAQs in ``data/faq.json``. ``match_faq`` scores a user's
issue description against each entry's keywords and returns the best hit.
"""
import json
import os
import re

_FAQ_PATH = os.path.join(os.path.dirname(__file__), "data", "faq.json")
_FAQ_CACHE: list[dict] | None = None


def load_faqs() -> list[dict]:
    global _FAQ_CACHE
    if _FAQ_CACHE is None:
        try:
            with open(_FAQ_PATH, "r", encoding="utf-8") as fh:
                _FAQ_CACHE = (json.load(fh) or {}).get("entries", []) or []
        except Exception:
            _FAQ_CACHE = []
    return _FAQ_CACHE


def match_faq(text: str) -> dict | None:
    """Return the best-matching FAQ entry for an issue description, or None.

    Score = number of distinct keywords from the entry found in the text.
    Ties break toward the earlier entry.
    """
    lower = (text or "").lower()
    if not lower.strip():
        return None
    best: dict | None = None
    best_score = 0
    for entry in load_faqs():
        score = 0
        for kw in entry.get("keywords", []):
            kw_l = kw.lower()
            if " " in kw_l:
                if kw_l in lower:
                    score += 1
            elif re.search(rf"\b{re.escape(kw_l)}\b", lower):
                score += 1
        if score > best_score:
            best_score = score
            best = entry
    return best if best_score > 0 else None


def format_steps(entry: dict) -> str:
    steps = entry.get("steps", []) or []
    return "\n".join(f"{i}. {s}" for i, s in enumerate(steps, start=1))
