from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class InvokeRequest(BaseModel):
    message: str
    thread_id: str


@router.post("/agents/agent-one/invoke")
def invoke(request: InvokeRequest):
    return {"answer": "stub", "speak": "stub"}
