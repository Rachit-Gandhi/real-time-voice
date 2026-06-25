"""Feedback loop — run directly: python tests/loop.py"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, "D:/real-time-voice/server")

# Load root .env so OPENAI_API_KEY is available
from dotenv import load_dotenv
load_dotenv("D:/real-time-voice/.env", override=False)

from unittest.mock import patch, MagicMock

FAKE_CTX = {
    "wwts_session": 9999,
    "customer_codes": [{"code": "DELLQXS", "name": "Dell QXS"}],
}

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

results = []

def check(name, cond, detail=""):
    tag = PASS if cond else FAIL
    results.append(cond)
    print(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))


def fresh_graph():
    # Re-import each time to get a fresh MemorySaver
    import importlib
    import wwts_agent.graph as gmod
    importlib.reload(gmod)
    return gmod.build_wwts_graph()


def invoke(g, tid, msg, ctx=None):
    """Fixed invoke — no messages reset."""
    config = {"configurable": {"thread_id": tid}}
    return g.invoke(
        {
            "user_message": msg,
            "thread_id": tid,
            "user_id": "TESTUSER",
            "context": ctx or FAKE_CTX,
            # messages omitted intentionally
        },
        config=config,
    )


def invoke_fixed(g, tid, msg, ctx=None):
    """Invoke WITHOUT resetting messages — the proposed fix."""
    config = {"configurable": {"thread_id": tid}}
    return g.invoke(
        {
            "user_message": msg,
            "thread_id": tid,
            "user_id": "TESTUSER",
            "context": ctx or FAKE_CTX,
            # no "messages" key
        },
        config=config,
    )


# ── Hypothesis 1: messages reset ──────────────────────────────────────────────
print("\n=== H1: messages reset on every call ===")
with patch("wwts_agent.nodes.execute.api.list_workorders",
           return_value={"success": True, "orders": [], "count": 0}):
    g = fresh_graph()
    s1 = invoke(g, "h1-a", "Hi")
    msgs_after_turn1 = len(s1.get("messages") or [])
    s2 = invoke(g, "h1-a", "List my work orders")
    msgs_after_turn2 = len(s2.get("messages") or [])

check("Turn 1 builds message history",
      msgs_after_turn1 >= 2,
      f"messages after turn 1: {msgs_after_turn1}")
check("Turn 2 RETAINS turn-1 messages (fails = reset bug)",
      msgs_after_turn2 >= 4,
      f"messages after turn 2: {msgs_after_turn2} (expected >=4)")

# ── Hypothesis 2: first message never reaches executing_list ──────────────────
print("\n=== H2: first non-greeting goes directly to executing_list ===")
with patch("wwts_agent.nodes.execute.api.list_workorders",
           return_value={"success": True, "orders": [], "count": 0}):
    g = fresh_graph()
    s = invoke(g, "h2-a", "How many open work orders are there?")

check("Stage is 'done' (passed through execute)",
      s.get("stage") == "done",
      f"stage={s.get('stage')!r}  answer={s.get('final_answer','')[:80]!r}")

# ── Hypothesis 3: 'Yes' after confirmation understood in context ───────────────
print("\n=== H3: 'Yes' is understood in context of prior question ===")
with patch("wwts_agent.nodes.execute.api.list_workorders",
           return_value={"success": True, "orders": [], "count": 0}):
    g = fresh_graph()
    # Needs the prior context that established "list WOs per customer"
    invoke(g, "h3-a", "Can you list open work orders grouped by customer code?")
    invoke(g, "h3-a", "Do it for Dell QXS")
    s = invoke(g, "h3-a", "Yes.")

check("Stage is 'done' after 'Yes' (not stuck in intent/greeting)",
      s.get("stage") == "done",
      f"stage={s.get('stage')!r}  answer={s.get('final_answer','')[:80]!r}")

# ── Hypothesis 4: fixed invoke preserves messages ─────────────────────────────
print("\n=== H4: fixed invoke (no messages=[]) preserves history ===")
with patch("wwts_agent.nodes.execute.api.list_workorders",
           return_value={"success": True, "orders": [], "count": 0}):
    g = fresh_graph()
    invoke_fixed(g, "h4-a", "Hi")
    s2 = invoke_fixed(g, "h4-a", "List my work orders")
    msgs_fixed = len(s2.get("messages") or [])

check("Messages preserved with fix",
      msgs_fixed >= 4,
      f"messages: {msgs_fixed}")

# ── Summary ──────────────────────────────────────────────────────────────────
total = len(results)
passed = sum(results)
print(f"\n{'='*50}")
print(f"  {passed}/{total} passed")
print(f"{'='*50}\n")
sys.exit(0 if passed == total else 1)
