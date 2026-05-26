import os
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

# Load .env from agent-one/ directory if present
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)
