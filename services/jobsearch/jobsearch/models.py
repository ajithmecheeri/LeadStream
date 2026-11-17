"""The service's tables (docs/jobsearch-plan-discovery.md, section 8). None of them holds user data."""

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, BigInteger, Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from jobsearch.db import Base

SYSTEMS = (
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "workday",
    "oracle",
    "eightfold",
    "careers_page",
)


class Employer(Base):
    __tablename__ = "employers"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(Text)
    careers_url: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str] = mapped_column(Text, default="IN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmployerBoard(Base):
    """An employer's job board on one hiring system. `board` is the system's id for it: "okta" on Greenhouse;
    "host/tenant/site" on Workday ("nvidia.wd5.myworkdayjobs.com/nvidia/NVIDIAExternalCareerSite")."""

    __tablename__ = "employer_boards"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    employer_id: Mapped[UUID] = mapped_column(ForeignKey("employers.id", ondelete="CASCADE"))
    system: Mapped[str] = mapped_column(Text)
    board: Mapped[str] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    jobs_total: Mapped[int | None] = mapped_column(Integer)  # every posting on the board, anywhere
    jobs_in_scope: Mapped[int | None] = mapped_column(Integer)  # in the service's country
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SearchArea(Base):
    """A (location, role family) pair some users want, with example titles. Sent by the app, aggregated."""

    __tablename__ = "search_areas"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    location: Mapped[str] = mapped_column(Text)
    role_family: Mapped[str] = mapped_column(Text)
    titles: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    active: Mapped[bool] = mapped_column(default=True)
    last_api_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Listing(Base):
    """A normalised job. `status`: pending (seen, details not read yet: not announced), active, closed."""

    __tablename__ = "listings"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    employer_id: Mapped[UUID | None] = mapped_column(ForeignKey("employers.id", ondelete="SET NULL"))
    board_id: Mapped[UUID | None] = mapped_column(ForeignKey("employer_boards.id", ondelete="SET NULL"))
    company: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    work_model: Mapped[str | None] = mapped_column(Text)
    experience: Mapped[str | None] = mapped_column(Text)
    salary: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    skills: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    requisition_id: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, default="active")
    missed_checks: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ListingSource(Base):
    __tablename__ = "listing_sources"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(Text)
    source_job_id: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    apply_url: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ListingVersion(Base):
    """A listing as it was before a material change (UPDATED or REPOSTED with new content)."""

    __tablename__ = "listing_versions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    replaced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Event(Base):
    """NEW / UPDATED / REPOSTED / CLOSED. The id is the feed cursor (ordered: see db.lock_events)."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(Text)
    listing_id: Mapped[UUID] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConnectorRun(Base):
    __tablename__ = "connector_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    connector: Mapped[str] = mapped_column(Text)  # greenhouse | … | workday | adzuna
    board_id: Mapped[UUID | None] = mapped_column(ForeignKey("employer_boards.id", ondelete="CASCADE"))
    search_area_id: Mapped[UUID | None] = mapped_column(ForeignKey("search_areas.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    found: Mapped[int] = mapped_column(Integer, default=0)
    new: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    reposted: Mapped[int] = mapped_column(Integer, default=0)
    closed: Mapped[int] = mapped_column(Integer, default=0)
    pending: Mapped[int] = mapped_column(Integer, default=0)  # seen, details still to read
    error: Mapped[str | None] = mapped_column(Text)


class BoardPage(Base):
    """A careers-site page read and found outside the service's country (or not a job): not read again until
    `careers_skip_days` have passed (decision 13)."""

    __tablename__ = "board_pages"
    board_id: Mapped[UUID] = mapped_column(
        ForeignKey("employer_boards.id", ondelete="CASCADE"), primary_key=True
    )
    page_id: Mapped[str] = mapped_column(Text, primary_key=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiQuota(Base):
    __tablename__ = "api_quota"
    api: Mapped[str] = mapped_column(Text, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    calls: Mapped[int] = mapped_column(Integer, default=0)
