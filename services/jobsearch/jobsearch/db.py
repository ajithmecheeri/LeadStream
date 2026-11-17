"""Database: one async engine for the service's own database. No user data, so no row-level security."""

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from jobsearch.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_maker: async_sessionmaker[AsyncSession] | None = None


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _engine, _maker
    if _maker is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
        _maker = async_sessionmaker(_engine, expire_on_commit=False)
    return _maker


async def dispose_engine() -> None:
    global _engine, _maker
    if _engine is not None:
        await _engine.dispose()
    _engine, _maker = None, None


async def session() -> AsyncIterator[AsyncSession]:
    """A request's transaction (FastAPI dependency): committed when the route returns, rolled back on error."""
    async with sessionmaker()() as db, db.begin():
        yield db


EVENTS_LOCK = 4_000_201  # advisory lock key: see lock_events


async def lock_events(db: AsyncSession) -> None:
    """Writers of events take this lock for the rest of their transaction, so event ids commit in order and a
    reader's cursor never skips an event that commits late (decision 3)."""
    await db.execute(text("select pg_advisory_xact_lock(:k)"), {"k": EVENTS_LOCK})
