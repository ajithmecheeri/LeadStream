"""Test setup: a real Postgres (the jobsearch_test database), rebuilt with Alembic once per session and
truncated between tests. Tests marked `nodb` (the connectors' readers) run without it. No test calls a real
job board or API: HTTP goes through httpx.MockTransport."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

os.environ["JOBSEARCH_ENV"] = "test"
os.environ["JOBSEARCH_DATABASE_URL"] = os.environ.get(
    "JOBSEARCH_TEST_DATABASE_URL",
    "postgresql+asyncpg://jobsearch_app:jobsearch_app@localhost:5432/jobsearch_test",
)
os.environ["JOBSEARCH_MIGRATIONS_DATABASE_URL"] = os.environ.get(
    "JOBSEARCH_TEST_MIGRATIONS_DATABASE_URL",
    "postgresql+asyncpg://jobsearch:jobsearch@localhost:5432/jobsearch_test",
)
os.environ["JOBSEARCH_TOKEN"] = TOKEN = "test-service-token"
for key in ("JOBSEARCH_ADZUNA_APP_ID", "JOBSEARCH_ADZUNA_APP_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
    os.environ[key] = ""

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from jobsearch.config import get_settings  # noqa: E402
from jobsearch.db import dispose_engine  # noqa: E402
from jobsearch.main import create_app  # noqa: E402

get_settings.cache_clear()
FIXTURES = Path(__file__).parent / "fixtures"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def _alembic(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
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
    if request.node.get_closest_marker("nodb"):
        yield
        return
    request.getfixturevalue("schema")
    yield
    await dispose_engine()
    eng = create_async_engine(os.environ["JOBSEARCH_MIGRATIONS_DATABASE_URL"])
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "truncate employers, employer_boards, search_areas, listings, listing_sources, listing_versions, "
                "events, connector_runs, api_quota, procrastinate_jobs, procrastinate_workers, "
                "procrastinate_periodic_defers restart identity cascade"
            )
        )
    await eng.dispose()


@pytest.fixture
async def api():
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        c.headers.update(HEADERS)
        yield c


def sample(name: str):
    import json

    return json.loads((FIXTURES / name).read_text())
