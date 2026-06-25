"""Persist and load WWTS login enrichment by portal session id."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from database import SessionLocal
from models import WwtsLoginSession


def save_login_session(
    *,
    user_id: str,
    wwts_session: int,
    user_name: str = "",
    user_type: str = "",
    authorized_functions: list[str] | None = None,
    customer_codes: list[dict[str, str]] | None = None,
) -> None:
    """Upsert login enrichment for a WWTS portal session."""
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        row = db.query(WwtsLoginSession).filter_by(wwts_session=wwts_session).first()
        if row is None:
            row = WwtsLoginSession(
                user_id=user_id,
                wwts_session=wwts_session,
                logged_in_at=now,
            )
            db.add(row)
        row.user_id = user_id
        row.user_name = user_name or ""
        row.user_type = user_type or ""
        row.authorized_functions = list(authorized_functions or [])
        row.customer_codes = list(customer_codes or [])
        row.logged_in_at = now
        db.commit()


def get_login_session(wwts_session: int) -> dict[str, Any] | None:
    """Load stored login context for invoke enrichment."""
    with SessionLocal() as db:
        row = db.query(WwtsLoginSession).filter_by(wwts_session=wwts_session).first()
        if row is None:
            return None
        return {
            "user_id": row.user_id,
            "wwts_session": row.wwts_session,
            "user_name": row.user_name,
            "user_type": row.user_type,
            "authorized_functions": list(row.authorized_functions or []),
            "customer_codes": list(row.customer_codes or []),
            "logged_in_at": row.logged_in_at.isoformat() if row.logged_in_at else None,
        }
