"""Alembic runs as the service's schema owner (JOBSEARCH_MIGRATIONS_DATABASE_URL), never as its app role."""

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from jobsearch.config import get_settings
from jobsearch.models import Base

target_metadata = Base.metadata


def _run(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(get_settings().migrations_database_url)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=get_settings().migrations_database_url, target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
