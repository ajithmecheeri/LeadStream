"""Settings loaded from environment variables (see .env.example at the repo root)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    env: str = Field("local", description="local | test | prod")
    app_name: str = "BrewMyJob"
    public_base_url: str = "http://localhost:3000"

    # The API connects as a NON-superuser role so row-level security applies.
    database_url: str = "postgresql+asyncpg://fitfirst_app:fitfirst_app@localhost:5432/fitfirst"
    # Migrations run as the schema owner.
    migrations_database_url: str = "postgresql+asyncpg://fitfirst:fitfirst@localhost:5432/fitfirst"

    # Ed25519 keys, PEM. Leave empty locally: a key is generated at startup (tokens die on restart).
    jwt_private_key: str = ""
    jwt_public_key: str = ""
    jwt_issuer: str = "fitfirst"
    access_token_minutes: int = 15
    # Accounts whose email matches this pattern use the app without a plan (the e2e tests and the demo on a
    # local stack; empty in production). docs/plan-roles-and-plans.md, decision 6.
    free_access_emails: str = ""
    refresh_token_days: int = 30

    # Domain used to build each user's alert-forwarding address: alerts-<token>@<inbound_domain>
    inbound_domain: str = "in.fitfirst.local"
    # Shared with the Cloudflare Email Worker: it signs each forwarded email with HMAC-SHA256.
    # Empty means /internal/inbound rejects everything.
    inbound_hmac_secret: str = ""
    inbound_max_bytes: int = 5_000_000

    # The Job Search Service (services/jobsearch): company boards, Workday and job APIs (Adzuna's key is set
    # there now). The app pulls its event feed; the token is shared with the service (JOBSEARCH_TOKEN).
    jobsearch_url: str = "http://localhost:8100"
    jobsearch_token: str = "local-dev-jobsearch-token"
    jobsearch_timeout_seconds: float = 120.0  # a check of one Workday board can take a minute

    # Milestone 6: WhatsApp alerts through Meta's WhatsApp Business (Cloud) API. Empty: messages are written to
    # the worker log instead of sent. Templates must be approved in WhatsApp Manager (docs/plan-m6.md).
    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_api_version: str = "v21.0"
    whatsapp_job_template: str = "job_alert"
    whatsapp_code_template: str = "verify_code"
    whatsapp_template_language: str = "en"

    # Raw alert emails are kept this long (to re-parse after a parser fix), then deleted.
    raw_email_retention_days: int = 90

    # Resumes and cover letters: largest upload accepted.
    document_max_bytes: int = 5_000_000

    # AI. Empty keys are fine: each task then uses its rule-based fallback (see app/modules/llm).
    anthropic_api_key: str = ""
    voyage_api_key: str = ""
    voyage_model: str = "voyage-4-lite"
    # Most text one scoring run sends to Voyage; the rest follows a minute later. 8K fits a key without a
    # payment method (10K tokens a minute); raise it (e.g. 500000) once billing is set up.
    voyage_tokens_per_run: int = 8_000
    embedding_dims: int = 1024  # must match the vector(1024) columns
    # Per user per day; once reached, AI calls fall back to rules until the next UTC day.
    llm_daily_cost_cap_usd: float = 1.0

    cors_origins: list[str] = ["http://localhost:3000"]
    cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
