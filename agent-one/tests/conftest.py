import os
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

_SEED_DOCS = [
    {
        "url": "https://test.example/services",
        "title": "Services",
        "content": "We offer grocery delivery, in-store pick-up, and customer support.",
        "website_id": "demo-site",
    },
    {
        "url": "https://test.example/refund-policy",
        "title": "Refund Policy",
        "content": "Refunds for grocery orders are processed within 5 to 7 business days.",
        "website_id": "demo-site",
    },
]


@pytest.fixture(autouse=True)
def _isolated_pipeline(tmp_path, monkeypatch):
    """Give each test its own SQLite index, a fresh pipeline singleton, and hash embedder.

    Blanking OPENAI_API_KEY keeps make_embedder() deterministic and avoids API calls
    in unit tests. DATABASE_URL is blanked so tests use MockBusinessApiTools, not the
    real grocery DB (which needs a live API key for SQL generation).
    Integration tests that genuinely need a real key should override this fixture.
    """
    monkeypatch.setenv("INDEX_DB_PATH", str(tmp_path / "test_index.db"))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("DATABASE_URL", "")
    import app.retrieval as _ret
    from app.retrieval.pipeline import WebsiteDocument
    _ret.reset_default_pipeline()
    pipeline = _ret.get_default_pipeline()
    pipeline.ingest_documents([WebsiteDocument(**d) for d in _SEED_DOCS])
    yield
    _ret.reset_default_pipeline()



@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)
