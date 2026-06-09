"""WWTS login session persistence."""
import sys
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from database import Base, SessionLocal, engine, init_db
from models import WwtsLoginSession
from wwts_session_store import get_login_session, save_login_session


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    url = f"sqlite:///{db_file}"
    monkeypatch.setenv("WWTS_DATABASE_URL", url)
    import database as db_mod
    import models as models_mod
    import wwts_session_store as store_mod

    db_mod.DATABASE_URL = url
    db_mod.engine = __import__("sqlalchemy").create_engine(url, connect_args={"check_same_thread": False})
    from sqlalchemy.orm import sessionmaker

    db_mod.SessionLocal = sessionmaker(bind=db_mod.engine, autoflush=False, autocommit=False)
    models_mod.Base = db_mod.Base
    store_mod.SessionLocal = db_mod.SessionLocal
    db_mod.Base.metadata.create_all(bind=db_mod.engine)
    yield


def test_save_and_load_login_session():
    save_login_session(
        user_id="RSMITH",
        wwts_session=45270812,
        user_name="Rick Smith",
        user_type="CSR",
        authorized_functions=["RequestForOpen", "CloseCall"],
        customer_codes=[{"code": "DELLQXS", "name": "Dell"}],
    )
    loaded = get_login_session(45270812)
    assert loaded is not None
    assert loaded["user_id"] == "RSMITH"
    assert loaded["user_name"] == "Rick Smith"
    assert "RequestForOpen" in loaded["authorized_functions"]
    assert loaded["customer_codes"][0]["code"] == "DELLQXS"
