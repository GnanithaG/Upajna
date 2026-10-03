import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """App running fully offline: mocked Claude, job APIs and browser; throwaway SQLite database."""
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    monkeypatch.setenv("SESSION_SECRET", "s")
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("APPLY_SUBMIT", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    from app.config import get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
