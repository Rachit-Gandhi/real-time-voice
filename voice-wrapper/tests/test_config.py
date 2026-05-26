"""Tests for runtime configuration loading."""
from apps.api.config import Settings


def test_settings_defaults():
    settings = Settings()
    assert settings.realtime_model == "gpt-4o-realtime-preview"
    assert settings.realtime_voice == "marin"
    assert settings.realtime_client_secret_ttl_seconds == 600
    assert settings.agent_one_base_url == "http://localhost:8001"
