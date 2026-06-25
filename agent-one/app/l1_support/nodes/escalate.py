import json
from pathlib import Path

from app.l1_support.state import L1SupportState

_MATRIX_PATH = Path(__file__).parent.parent / "data" / "escalation_matrix.json"


def _load_matrix() -> dict:
    with open(_MATRIX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _find_best_rule(issue_text: str, rules: list[dict]) -> dict | None:
    """Find the highest-priority rule whose keywords appear in the issue text."""
    lower_issue = issue_text.lower()
    # Sort rules by priority ascending (1 = highest)
    sorted_rules = sorted(rules, key=lambda r: r.get("priority", 99))
    for rule in sorted_rules:
        keywords = rule.get("keywords", [])
        if any(kw.lower() in lower_issue for kw in keywords):
            return rule
    return None


def escalate(state: L1SupportState) -> L1SupportState:
    matrix = _load_matrix()
    rules = matrix.get("rules", [])
    default = matrix.get("default", {})

    collected = state.get("collected") or {}
    ticket_details = state.get("ticket_details") or {}

    # Build a combined text to match against keywords
    issue_text = " ".join(filter(None, [
        collected.get("issue", ""),
        state.get("user_message", ""),
        ticket_details.get("issue", ""),
    ]))

    matched_rule = _find_best_rule(issue_text, rules) if issue_text.strip() else None

    if matched_rule:
        return {
            **state,
            "escalation_team": matched_rule["team"],
            "escalation_contact": matched_rule["contact"],
            "escalation_sla_hours": matched_rule["response_sla_hours"],
        }

    return {
        **state,
        "escalation_team": default.get("team", "General Support"),
        "escalation_contact": default.get("contact", "support@company.com"),
        "escalation_sla_hours": default.get("response_sla_hours", 24),
    }
