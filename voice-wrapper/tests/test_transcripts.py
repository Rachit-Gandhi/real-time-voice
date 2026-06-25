"""Tests for transcript persistence (store + API)."""
from fastapi.testclient import TestClient
import pytest

from apps.api.storage.transcript_store import TranscriptStore


# ---------------- Store unit tests ----------------

def test_store_save_and_get_roundtrip(tmp_path):
    store = TranscriptStore(tmp_path / "t.db")
    summary = store.save(
        turns=[
            {"role": "agent", "text": "Hi, may I have your name?"},
            {"role": "user", "text": "Rohit"},
            {"role": "agent", "text": "Nice to meet you, Rohit."},
        ],
        user_id="u1",
        user_name="Rohit G",
        mode="voice",
    )
    assert summary["turn_count"] == 3
    assert summary["preview"].startswith("Hi, may I have")
    assert "turns" not in summary  # list/summary form omits full turns

    full = store.get(summary["id"])
    assert full["turns"][1] == {"role": "user", "text": "Rohit"}
    assert full["user_name"] == "Rohit G"


def test_store_drops_empty_turns(tmp_path):
    store = TranscriptStore(tmp_path / "t.db")
    summary = store.save(turns=[{"role": "user", "text": "  "}, {"role": "agent", "text": "Hello"}])
    assert summary["turn_count"] == 1


def test_store_list_filters_by_user_and_orders_newest_first(tmp_path):
    store = TranscriptStore(tmp_path / "t.db")
    store.save(turns=[{"role": "user", "text": "first"}], user_id="a")
    store.save(turns=[{"role": "user", "text": "second"}], user_id="a")
    store.save(turns=[{"role": "user", "text": "other"}], user_id="b")

    a_items = store.list(user_id="a")
    assert [i["preview"] for i in a_items] == ["second", "first"]
    assert len(store.list()) == 3


def test_store_delete(tmp_path):
    store = TranscriptStore(tmp_path / "t.db")
    s = store.save(turns=[{"role": "user", "text": "x"}])
    assert store.delete(s["id"]) is True
    assert store.get(s["id"]) is None
    assert store.delete(s["id"]) is False


# ---------------- API tests ----------------

@pytest.fixture
def client(tmp_path):
    from apps.api.main import app

    app.state.transcript_store = TranscriptStore(tmp_path / "api.db")
    return TestClient(app)


def test_api_create_list_get_delete(client):
    payload = {
        "turns": [
            {"role": "agent", "text": "How can I help?"},
            {"role": "user", "text": "List my work orders"},
        ],
        "user_id": "u9",
        "user_name": "Dave",
        "mode": "chat",
    }
    created = client.post("/transcripts", json=payload).json()
    assert created["turn_count"] == 2
    tid = created["id"]

    listing = client.get("/transcripts", params={"user_id": "u9"}).json()
    assert any(item["id"] == tid for item in listing)

    full = client.get(f"/transcripts/{tid}").json()
    assert full["turns"][0]["text"] == "How can I help?"
    assert full["mode"] == "chat"

    assert client.delete(f"/transcripts/{tid}").json()["deleted"] is True
    assert client.get(f"/transcripts/{tid}").status_code == 404


def test_api_rejects_empty_transcript(client):
    res = client.post("/transcripts", json={"turns": [{"role": "user", "text": "   "}]})
    assert res.status_code == 400
