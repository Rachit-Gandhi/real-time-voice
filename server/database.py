"""SQLAlchemy engine and session factory for server-side persistence."""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

_DEFAULT_SQLITE = Path(__file__).resolve().parent / "data" / "wwts_auth.db"
DATABASE_URL = os.getenv(
    "WWTS_DATABASE_URL",
    f"sqlite:///{_DEFAULT_SQLITE.as_posix()}",
)

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}


class Base(DeclarativeBase):
    pass


engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Path(_DEFAULT_SQLITE).parent.mkdir(parents=True, exist_ok=True)
    # Import models so metadata is populated before create_all.
    from models import WwtsLoginSession  # noqa: F401

    Base.metadata.create_all(bind=engine)
