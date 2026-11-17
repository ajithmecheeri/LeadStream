"""Database engine and per-request sessions.

Every request that acts for a signed-in user runs inside one transaction that starts with
`SET LOCAL app.user_id = '<uuid>'`. Postgres row-level security policies on private tables
compare `user_id` against that setting, so a query can never see another user's rows even if
application code forgets a WHERE clause.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def engine():
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True, pool_size=5)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine, _sessionmaker = None, None


async def set_user(session: AsyncSession, user_id: UUID) -> None:
    """Scope the current transaction to one user for row-level security."""
    await session.execute(text("select set_config('app.user_id', :uid, true)"), {"uid": str(user_id)})


@asynccontextmanager
async def user_scope(user_id: UUID) -> AsyncIterator[AsyncSession]:
    """A transaction scoped to one user, for code outside a request (worker tasks, the inbound endpoint)."""
    async with sessionmaker()() as session, session.begin():
        await set_user(session, user_id)
        yield session


async def get_session() -> AsyncIterator[AsyncSession]:
    """Unscoped session: only for auth endpoints that touch tables without RLS."""
    async with sessionmaker()() as session, session.begin():
        yield session
