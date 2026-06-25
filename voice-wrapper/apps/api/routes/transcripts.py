"""Routes for saving and viewing call/chat transcripts."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/transcripts", tags=["transcripts"])


class TurnIn(BaseModel):
    role: str
    text: str


class TranscriptCreate(BaseModel):
    turns: list[TurnIn]
    user_id: str = ""
    user_name: str = ""
    agent_id: str = "wwts"
    mode: str = "voice"
    started_at: str | None = None
    ended_at: str | None = None


@router.post("")
def create_transcript(body: TranscriptCreate, request: Request):
    turns = [{"role": t.role, "text": t.text} for t in body.turns]
    if not any(t["text"].strip() for t in turns):
        raise HTTPException(status_code=400, detail="Transcript has no content to save")
    store = request.app.state.transcript_store
    return store.save(
        turns=turns,
        user_id=body.user_id,
        user_name=body.user_name,
        agent_id=body.agent_id,
        mode=body.mode,
        started_at=body.started_at,
        ended_at=body.ended_at,
    )


@router.get("")
def list_transcripts(request: Request, user_id: str | None = None, limit: int = 200):
    store = request.app.state.transcript_store
    return store.list(user_id=user_id, limit=limit)


@router.get("/{transcript_id}")
def get_transcript(transcript_id: str, request: Request):
    store = request.app.state.transcript_store
    record = store.get(transcript_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return record


@router.delete("/{transcript_id}")
def delete_transcript(transcript_id: str, request: Request):
    store = request.app.state.transcript_store
    if not store.delete(transcript_id):
        raise HTTPException(status_code=404, detail="Transcript not found")
    return {"id": transcript_id, "deleted": True}
