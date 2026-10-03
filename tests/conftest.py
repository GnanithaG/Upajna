import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def get_settings_fresh():
    from app.config import get_settings
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """App running fully offline: mocked Claude, job APIs and browser; a throwaway database."""
    monkeypatch.setenv("APP_PASSWORD", "test-pass")
    monkeypatch.setenv("SESSION_SECRET", "s")
    monkeypatch.setenv("MOCK_EXTERNAL", "true")
    monkeypatch.setenv("APPLY_SUBMIT", "false")
    # Tests use a throwaway SQLite file. Set TEST_DATABASE_URL to run them against Postgres instead
    # (CI does this, so the production database is tested too).
    pg = os.environ.get("TEST_DATABASE_URL")
    monkeypatch.setenv("DATABASE_URL", pg or f"sqlite:///{tmp_path}/test.db")
    if pg:
        from app import db
        db.init_db(get_settings_fresh().sqlalchemy_url)
        db.Base.metadata.drop_all(db._engine)
    from app.config import get_settings
    get_settings.cache_clear()
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
