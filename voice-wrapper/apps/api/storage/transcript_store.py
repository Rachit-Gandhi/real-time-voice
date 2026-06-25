"""SQLite-backed store for saved call/chat transcripts.

A transcript is a single completed conversation (voice call or text chat). The
full turn list is stored as JSON; lightweight summary columns are duplicated so
the dashboard list view can render without parsing every blob.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_PREVIEW_LEN = 160


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _preview(turns: list[dict]) -> str:
    for turn in turns:
        text = str(turn.get("text") or "").strip()
        if text:
            return text[:_PREVIEW_LEN]
    return ""


class TranscriptStore:
    """Thread-safe SQLite store. One connection guarded by a lock — call volume
    here is tiny (one write per ended call), so a global lock is simplest."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS transcripts (
                    id          TEXT PRIMARY KEY,
                    user_id     TEXT,
                    user_name   TEXT,
                    agent_id    TEXT,
                    mode        TEXT,
                    started_at  TEXT,
                    ended_at    TEXT,
                    turn_count  INTEGER,
                    preview     TEXT,
                    turns_json  TEXT,
                    created_at  TEXT
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_transcripts_user "
                "ON transcripts (user_id, created_at)"
            )
            self._conn.commit()

    def save(
        self,
        *,
        turns: list[dict],
        user_id: str = "",
        user_name: str = "",
        agent_id: str = "wwts",
        mode: str = "voice",
        started_at: str | None = None,
        ended_at: str | None = None,
    ) -> dict[str, Any]:
        clean = [
            {"role": str(t.get("role") or "agent"), "text": str(t.get("text") or "").strip()}
            for t in (turns or [])
            if str(t.get("text") or "").strip()
        ]
        record_id = str(uuid.uuid4())
        now = _now_iso()
        row = {
            "id": record_id,
            "user_id": user_id or "",
            "user_name": user_name or "",
            "agent_id": agent_id or "wwts",
            "mode": mode or "voice",
            "started_at": started_at or now,
            "ended_at": ended_at or now,
            "turn_count": len(clean),
            "preview": _preview(clean),
            "turns_json": json.dumps(clean),
            "created_at": now,
        }
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO transcripts
                    (id, user_id, user_name, agent_id, mode, started_at, ended_at,
                     turn_count, preview, turns_json, created_at)
                VALUES
                    (:id, :user_id, :user_name, :agent_id, :mode, :started_at, :ended_at,
                     :turn_count, :preview, :turns_json, :created_at)
                """,
                row,
            )
            self._conn.commit()
        return self._summary(row)

    def list(self, *, user_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        query = "SELECT * FROM transcripts"
        params: list[Any] = []
        if user_id:
            query += " WHERE user_id = ?"
            params.append(user_id)
        # created_at is microsecond ISO-8601, which sorts correctly as text;
        # rowid breaks any same-timestamp tie so newest is always first.
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._summary(dict(r)) for r in rows]

    def get(self, transcript_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM transcripts WHERE id = ?", (transcript_id,)
            ).fetchone()
        if row is None:
            return None
        record = self._summary(dict(row))
        record["turns"] = json.loads(row["turns_json"] or "[]")
        return record

    def delete(self, transcript_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM transcripts WHERE id = ?", (transcript_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _summary(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "user_id": row.get("user_id", ""),
            "user_name": row.get("user_name", ""),
            "agent_id": row.get("agent_id", ""),
            "mode": row.get("mode", ""),
            "started_at": row.get("started_at"),
            "ended_at": row.get("ended_at"),
            "turn_count": row.get("turn_count", 0),
            "preview": row.get("preview", ""),
            "created_at": row.get("created_at"),
        }
