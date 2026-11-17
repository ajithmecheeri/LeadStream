"""Settings from environment variables (see .env.example at the repo root, "Job Search Service")."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"), env_prefix="JOBSEARCH_", extra="ignore"
    )

    env: str = "local"  # local | test | prod
    database_url: str = "postgresql+asyncpg://jobsearch_app:jobsearch_app@localhost:5432/jobsearch"
    migrations_database_url: str = "postgresql+asyncpg://jobsearch:jobsearch@localhost:5432/jobsearch"
    # Bearer token the main app sends. Empty: every /v1 call is refused (except in tests, which set one).
    token: str = ""
    country: str = "IN"  # India first (decision 2 in docs/plan-jobsearch-build.md)

    # Adzuna (free key at developer.adzuna.com). Read without the JOBSEARCH_ prefix too, so the key the app
    # already had in .env keeps working.
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    adzuna_daily_calls: int = 100  # stays under the free tier's daily limit

    workday_details_per_run: int = 150  # descriptions fetched per board per run; the rest on the next run
    careers_pages_per_run: int = 60  # new job pages read per careers site per run (decision 13)
    careers_skip_days: int = 30  # a careers page found outside India isn't read again for this long
    check_every_minutes: int = 10  # "check now" on one employer at most this often


@lru_cache
def get_settings() -> Settings:
    import os

    s = Settings()
    # Fall back to the app's ADZUNA_* names when the JOBSEARCH_ ones aren't set.
    if not s.adzuna_app_id and os.environ.get("ADZUNA_APP_ID"):
        s.adzuna_app_id = os.environ["ADZUNA_APP_ID"]
    if not s.adzuna_app_key and os.environ.get("ADZUNA_APP_KEY"):
        s.adzuna_app_key = os.environ["ADZUNA_APP_KEY"]
    return s
