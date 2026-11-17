from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Job(Base):
    """A job posting in the shared catalog. No user_id and no RLS: public posting data, stored once and
    linked to every user who received it (see UserJob). The app role can't delete catalog rows."""

    __tablename__ = "jobs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # sha256 of normalised company | title | location; None when the company is unknown or truncated.
    fingerprint: Mapped[str | None] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    work_model: Mapped[str | None] = mapped_column(Text)
    experience: Mapped[str | None] = mapped_column(Text)
    salary: Mapped[str | None] = mapped_column(Text)
    skills: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    description: Mapped[str | None] = mapped_column(Text)
    about_company: Mapped[str | None] = mapped_column(Text)
    offer: Mapped[str | None] = mapped_column(Text)
    description_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)  # labelled facts: industry, department…
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # False when only hand-forwarded alerts (no portal DKIM) have described it; see catalog.service.
    verified: Mapped[bool] = mapped_column(Boolean, default=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class JobSource(Base):
    """Where a catalog job was seen: one row per portal listing. `url` is public, without a query string."""

    __tablename__ = "job_sources"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(16))  # parsers/base.py: Source
    source_job_id: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)  # None for recruiter invites (no public page)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
