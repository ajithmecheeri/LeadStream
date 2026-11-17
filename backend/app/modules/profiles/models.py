from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class SearchProfile(Base):
    """A Skill Match profile: the roles, places, weights and skills one resume is matched with (user feedback
    2026-11-13: one per resume, made from it). `resume_skills` are read from the resume and refreshed with it;
    `skills` are the ones the user added by hand. A profile with no resume (made through the API only) is
    matched with every resume, as search profiles were before."""

    __tablename__ = "search_profiles"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    target_roles: Mapped[list[str]] = mapped_column(ARRAY(Text))
    locations: Mapped[list[str]] = mapped_column(ARRAY(Text))
    work_models: Mapped[list[str]] = mapped_column(ARRAY(Text))
    min_seniority: Mapped[int] = mapped_column(SmallInteger)
    excluded_companies: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    # Added by the user, as they wrote them.
    skills: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    resume_id: Mapped[UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"))
    resume_skills: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)  # read from the resume
    resume_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    weights: Mapped[dict] = mapped_column(JSONB)
    threshold: Mapped[int] = mapped_column(SmallInteger, default=85)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # FK to resumes is added in milestone 3 together with the resumes table.
    default_resume_id: Mapped[UUID | None]
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
