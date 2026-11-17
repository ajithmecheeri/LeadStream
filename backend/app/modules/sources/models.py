from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CompanyFeed(Base):
    """Before the Job Search Service (milestone 9): a company board the app read itself. Shared. Kept until the
    switch is confirmed; each row is exported once to the service with the same id (`exported_at`)."""

    __tablename__ = "company_feeds"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text)
    ats: Mapped[str] = mapped_column(Text)  # greenhouse | lever | ashby | smartrecruiters
    board: Mapped[str] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    jobs_total: Mapped[int | None] = mapped_column(Integer)
    jobs_india: Mapped[int | None] = mapped_column(Integer)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WatchedCompany(Base):
    """An employer the user follows: the Job Search Service's employer id (in its own database, so no foreign
    key) and the name, kept for when the service can't be reached. RLS: private."""

    __tablename__ = "watched_companies"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    employer_id: Mapped[UUID] = mapped_column()
    name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformCompany(Base):
    """The shared list of companies BrewMyJob reads for everyone, kept by the admins (user, 2026-11-17). Shared
    like the job catalog: no user data, no row level security."""

    __tablename__ = "platform_companies"
    employer_id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    added_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceRun(Base):
    """What a check or a pull of the event feed brought to the user, per employer (or Adzuna). RLS: private.

    `found`: jobs in India the source listed (or that arrived from it); `added`: new to the user; `skipped`: left
    out by the relevance check.
    """

    __tablename__ = "source_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(Text)  # company_feed | adzuna
    employer_id: Mapped[UUID | None] = mapped_column()
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    found: Mapped[int] = mapped_column(Integer, default=0)
    added: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    # The run's jobs: [{"job_id", "why"}], why = None when kept (Job sources → Last run → all jobs).
    jobs: Mapped[list] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text)


class JobSearchSync(Base):
    """Shared, one row: where the app is in the service's event feed, and the demand last sent."""

    __tablename__ = "jobsearch_sync"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    cursor: Mapped[int] = mapped_column(BigInteger, default=0)
    demand_hash: Mapped[str | None] = mapped_column(Text)
    pulled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    # The last pull that brought something: what Job sources shows as "Last run".
    last_pull_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_pull_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_pull_jobs: Mapped[int | None] = mapped_column(Integer)
    last_pull_new: Mapped[int | None] = mapped_column(Integer)
    last_pull_updated: Mapped[int | None] = mapped_column(Integer)
    last_pull_closed: Mapped[int | None] = mapped_column(Integer)
