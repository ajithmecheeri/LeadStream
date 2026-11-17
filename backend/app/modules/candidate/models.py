from datetime import datetime
from uuid import UUID

from sqlalchemy import ARRAY, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CandidateProfile(Base):
    """One per user: the facts every search profile shares. Private (RLS)."""

    __tablename__ = "candidate_profiles"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    headline: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    current_location: Mapped[str | None] = mapped_column(Text)
    years_experience: Mapped[int | None] = mapped_column(Integer)
    skills: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    domains: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    # Where the user wants to work (asked at sign-up, 2026-11-14): new match profiles start with these, and the
    # job search service looks for jobs there.
    job_locations: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    # Roles for Google Alerts (up to 5, set on Job sources); empty: the Skill Match profiles' target roles.
    alert_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    notice_days: Mapped[int | None] = mapped_column(Integer)
    current_ctc: Mapped[str | None] = mapped_column(Text)
    expected_ctc: Mapped[str | None] = mapped_column(Text)
    work_authorization: Mapped[str | None] = mapped_column(Text)
    linkedin_url: Mapped[str | None] = mapped_column(Text)
    # The user's own note for invitations on Networking (0023); not part of PUT /candidate.
    invite_note: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
