from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Application(Base):
    """A job the user applied for (they apply themselves; this records it). RLS: private.

    Created when the job is marked Applied. Status: applied → interviewing → offer → accepted, or rejected,
    withdrawn or no_response at any point.
    """

    __tablename__ = "applications"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user_job_id: Mapped[UUID] = mapped_column(ForeignKey("user_jobs.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(Text, default="applied")
    applied_on: Mapped[date] = mapped_column(Date)
    resume_id: Mapped[UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    cover_letter_id: Mapped[UUID | None] = mapped_column(ForeignKey("cover_letters.id", ondelete="SET NULL"))
    follow_up_on: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ApplicationEvent(Base):
    """One line of an application's timeline: applied, a status change, a note, a follow-up date. Private."""

    __tablename__ = "application_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    application_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)  # applied | status | note | follow_up
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobContact(Base):
    """Someone linked to one of the user's jobs: a recruiter or hiring manager the user found. Private.

    Saved only: BrewMyJob never messages anyone. Milestone 7 (networking) can link these to imported connections.
    """

    __tablename__ = "job_contacts"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user_job_id: Mapped[UUID] = mapped_column(ForeignKey("user_jobs.id", ondelete="CASCADE"))
    name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
