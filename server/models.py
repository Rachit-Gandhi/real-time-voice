"""ORM models for server persistence."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class WwtsLoginSession(Base):
    """WWTS portal session snapshot from a successful /gtaccess/login (no password)."""

    __tablename__ = "wwts_login_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    wwts_session: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    user_name: Mapped[str] = mapped_column(String(256), default="")
    user_type: Mapped[str] = mapped_column(String(64), default="")
    authorized_functions: Mapped[list] = mapped_column(JSON, default=list)
    customer_codes: Mapped[list] = mapped_column(JSON, default=list)
    logged_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
