from fastapi import APIRouter
from pydantic import BaseModel
from app.graph.graph import build_graph

router = APIRouter()
_graph = build_graph()


class InvokeRequest(BaseModel):
    message: str
    thread_id: str


@router.post("/agents/agent-one/invoke")
def invoke(request: InvokeRequest):
    state = _graph.invoke({
        "user_message": request.message,
        "thread_id": request.thread_id,
        "messages": [],
        "retrieved_chunks": [],
        "citations": [],
    })
    return {
        "answer": state.get("final_answer") or "",
        "speak": state.get("speak") or "",
    }
