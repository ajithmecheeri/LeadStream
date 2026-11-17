"""Test setup.

Tests run against a real Postgres (the `<db>_test` database), because row-level security is part of
what we test. The schema is rebuilt with Alembic once per session and tables are truncated between
tests. Set TEST_DATABASE_URL / TEST_MIGRATIONS_DATABASE_URL to point elsewhere.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://fitfirst_app:fitfirst_app@localhost:5432/fitfirst_test"
)
os.environ["MIGRATIONS_DATABASE_URL"] = os.environ.get(
    "TEST_MIGRATIONS_DATABASE_URL", "postgresql+asyncpg://fitfirst:fitfirst@localhost:5432/fitfirst_test"
)

os.environ["INBOUND_HMAC_SECRET"] = "test-inbound-secret"
# Test accounts (…@example.com) use the app without a plan; the plan tests use …@example.org.
os.environ["FREE_ACCESS_EMAILS"] = r"@example\.com$"
# Tests never call Voyage, Claude, Meta (WhatsApp) or Adzuna: keys from .env are blanked; tests that need them
# install fakes.
os.environ["VOYAGE_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = ""
os.environ["WHATSAPP_ACCESS_TOKEN"] = ""
os.environ["ADZUNA_APP_ID"] = ""
os.environ["ADZUNA_APP_KEY"] = ""

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import dispose_engine  # noqa: E402
from app.main import create_app  # noqa: E402

get_settings.cache_clear()


def _alembic(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        check=True,
        env=os.environ.copy(),
        capture_output=True,
    )


@pytest.fixture(scope="session")
def schema():
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    yield


@pytest.fixture(autouse=True)
async def clean_db(request):
    # Tests marked `nodb` (e.g. the email parsers) run without Postgres.
    if request.node.get_closest_marker("nodb"):
        yield
        return
    request.getfixturevalue("schema")
    yield
    await dispose_engine()
    eng = create_async_engine(os.environ["MIGRATIONS_DATABASE_URL"])
    async with eng.begin() as conn:
        # users cascades to every private table; the shared catalog and the task queue are listed.
        await conn.execute(
            text(
                "truncate users, audit_events, jobs, waitlist, company_feeds, jobsearch_sync, procrastinate_jobs, procrastinate_workers, "
                "procrastinate_periodic_defers restart identity cascade"
            )
        )
        # app_settings keeps its rows (migrations create them); put the defaults back.
        await conn.execute(
            text(
                "update app_settings set updated_by = null, value = case key "
                "when 'job_expiry_warn_days' then '30'::jsonb when 'job_expiry_auto_days' then '45'::jsonb "
                "else value end"
            )
        )
    await eng.dispose()


@pytest.fixture
async def client():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def unique_email() -> str:
    return f"user-{uuid.uuid4().hex[:8]}@example.com"


PASSWORD = "correct-horse-battery"


async def signup(client: httpx.AsyncClient, email: str | None = None, name: str = "Test User") -> dict:
    r = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": email or unique_email(),
            "first_name": name.split()[0],
            "last_name": " ".join(name.split()[1:]) or "Tester",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
            "accept_terms": True,
            "job_locations": ["Bengaluru"],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def user(client) -> dict:
    data = await signup(client)
    client.cookies.clear()
    return {**data, "headers": auth(data["access_token"])}


VALID_PROFILE = {
    "name": "VP Engineering",
    "target_roles": ["VP Engineering", "Head of Engineering"],
    "locations": ["Bengaluru", "Remote"],
    "work_models": ["Hybrid", "Remote"],
    "min_seniority": 5,
}


@pytest.fixture
async def account(client) -> dict:
    """A signed-in user with their forwarding address and id (for the ingestion and jobs tests)."""
    data = await signup(client)
    client.cookies.clear()
    headers = auth(data["access_token"])
    me = (await client.get("/api/v1/me", headers=headers)).json()
    return {"headers": headers, "address": me["forwarding_address"], "id": uuid.UUID(me["id"])}


async def set_role(email: str, role: str) -> None:
    """Change an account's role as the schema owner (there is no API for it), like `make admin`."""
    eng = create_async_engine(os.environ["MIGRATIONS_DATABASE_URL"])
    async with eng.begin() as conn:
        await conn.execute(text("update users set role = :r where email = :e"), {"r": role, "e": email})
    await eng.dispose()


async def admin_account(client, role: str = "admin") -> dict:
    """A signed-in admin (or super admin): signed up, given the role, signed in again for a token that says so."""
    email = unique_email()
    await signup(client, email)
    await set_role(email, role)
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    headers = auth(r.json()["access_token"])
    me = (await client.get("/api/v1/me", headers=headers)).json()
    assert me["role"] == role
    return {
        "headers": headers,
        "address": me["forwarding_address"],
        "id": uuid.UUID(me["id"]),
        "email": email,
    }


@pytest.fixture
async def super_admin(client) -> dict:
    return await admin_account(client, "super_admin")
