"""Runtime configuration for the voice wrapper API."""
from functools import lru_cache
from pathlib import Path
import os

from pydantic import BaseModel, Field


ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT_DIR / ".env"


def _load_dotenv(path: Path = ENV_FILE) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class Settings(BaseModel):
    openai_api_key: str | None = Field(default=None)
    realtime_model: str = "gpt-4o-realtime-preview"
    realtime_voice: str = "marin"
    realtime_client_secret_ttl_seconds: int = 600
    agent_one_base_url: str = "http://localhost:8001"


@lru_cache
def get_settings() -> Settings:
    env_file_values = _load_dotenv()

    def read(name: str, default: str | None = None) -> str | None:
        return os.getenv(name) or env_file_values.get(name) or default

    ttl = read("REALTIME_CLIENT_SECRET_TTL_SECONDS", "600")
    return Settings(
        openai_api_key=read("OPENAI_API_KEY"),
        realtime_model=read("REALTIME_MODEL", "gpt-4o-realtime-preview") or "gpt-4o-realtime-preview",
        realtime_voice=read("REALTIME_VOICE", "marin") or "marin",
        realtime_client_secret_ttl_seconds=int(ttl or "600"),
        agent_one_base_url=read("AGENT_ONE_BASE_URL", "http://localhost:8001")
        or "http://localhost:8001",
    )
