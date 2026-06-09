"""FastAPI routes for the WWTS agent."""
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from wwts_agent.graph import build_wwts_graph

router = APIRouter(tags=["wwts-agent"])
_graph = build_wwts_graph()


def _enrich_context_from_db(context: dict[str, Any]) -> dict[str, Any]:
    """Merge login enrichment from DB when invoke context is session-only."""
    session_id = context.get("wwts_session")
    if not session_id:
        return context
    try:
        server_dir = Path(__file__).resolve().parent.parent.parent / "server"
        server_path = str(server_dir)
        if server_path not in sys.path:
            sys.path.insert(0, server_path)
        from wwts_session_store import get_login_session  # noqa: WPS433

        stored = get_login_session(int(session_id))
    except Exception:
        return context
    if not stored:
        return context
    merged = dict(context)
    for key in ("authorized_functions", "user_name", "user_type", "customer_codes"):
        if not merged.get(key) and stored.get(key):
            merged[key] = stored[key]
    if not merged.get("user_id") and stored.get("user_id"):
        merged["user_id"] = stored["user_id"]
    return merged


class WWTSInvokeRequest(BaseModel):
    message: str
    thread_id: str
    user_id: str | None = None
    # context should contain (from /gtaccess/login via voice-wrapper):
    #   wwts_session: int              — session ID
    #   customer_codes: list           — [{code, name}, ...] for WO scope
    #   authorized_functions: list[str] — FunctionAuthorizeList names
    #   user_name: str                 — GetUserInfo display name
    #   user_type: str                 — GetUserInfo UserType
    context: dict[str, Any] = Field(default_factory=dict)


@router.post("/agents/wwts/invoke")
def wwts_invoke(request: WWTSInvokeRequest):
    context = _enrich_context_from_db(request.context)
    config = {"configurable": {"thread_id": request.thread_id}}
    state = _graph.invoke(
        {
            "user_message": request.message,
            "thread_id": request.thread_id,
            "user_id": request.user_id or context.get("user_id") or "",
            "context": context,
            # "messages" deliberately omitted — checkpoint preserves history
        },
        config=config,
    )
    return {
        "answer": state.get("final_answer", ""),
        "speak": state.get("speak") or state.get("final_answer", ""),
        "stage": state.get("stage", "greeting"),
        "intent": state.get("intent"),
        "wo_number": state.get("wo_number"),
        "wo_list": state.get("wo_list"),
        "created_wo_number": state.get("created_wo_number"),
        "wo_parts_count": len(state.get("wo_parts") or []),
        "wo_labor_count": len(state.get("wo_labor") or []),
        "wo_labor_activities_count": len(state.get("wo_labor_activities") or []),
        "wo_site": state.get("wo_site"),
        "wo_part_line": state.get("wo_part_line"),
        "search_filters": state.get("search_filters"),
        "requires_more_info": state.get("requires_more_info", True),
        "session_expired": state.get("session_expired", False),
    }
