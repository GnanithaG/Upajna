"""All configuration comes from environment variables (see .env.example)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    port: int = 8000
    app_password: str = ""
    session_secret: str = ""
    database_url: str = "sqlite:///./data/upajna.db"
    tz_name: str = "America/Los_Angeles"
    search_cron: str = "0 11,15,19 * * *"

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"
    claude_quick_model: str = "claude-haiku-4-5-20251001"

    jsearch_api_key: str = ""
    jsearch_host: str = "jsearch.p.rapidapi.com"
    jsearch_queries_per_run: int = 3
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""

    apply_submit: bool = False
    apply_max_per_run: int = 8

    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:you@example.com"

    mock_external: bool = False  # offline tests only: no Claude / job API / browser calls

    @property
    def sqlalchemy_url(self) -> str:
        url = self.database_url
        # Railway/Heroku style URLs → psycopg3 driver
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url

    def missing(self) -> list[str]:
        m = []
        if not self.app_password:
            m.append("APP_PASSWORD")
        if not self.session_secret:
            m.append("SESSION_SECRET")
        if not self.anthropic_api_key and not self.mock_external:
            m.append("ANTHROPIC_API_KEY")
        if not (self.jsearch_api_key or self.adzuna_app_id) and not self.mock_external:
            m.append("JSEARCH_API_KEY or ADZUNA_APP_ID/ADZUNA_APP_KEY")
        return m


@lru_cache
def get_settings() -> Settings:
    return Settings()
