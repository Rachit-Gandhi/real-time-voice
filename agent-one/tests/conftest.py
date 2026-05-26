import os
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))


@pytest.fixture(autouse=True)
def _isolated_pipeline(tmp_path, monkeypatch):
    """Give each test its own SQLite index, a fresh pipeline singleton, and hash embedder.

    Blanking OPENAI_API_KEY keeps make_embedder() deterministic and avoids API calls
    in unit tests. Integration tests that genuinely need a real key should override this
    fixture or set the var explicitly inside the test.
    """
    monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "test_index.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "")  # hash embedder in tests; no API calls
    import app.retrieval as _ret
    _ret.reset_default_pipeline()
    yield
    _ret.reset_default_pipeline()


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)
