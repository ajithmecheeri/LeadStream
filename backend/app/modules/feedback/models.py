from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class JobFeedback(Base):
    """One "Not for me" on a job, with the user's reason (milestone 13 A). RLS: private."""

    __tablename__ = "job_feedback"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user_job_id: Mapped[UUID] = mapped_column(ForeignKey("user_jobs.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text)  # feedback/learning.py: REASONS
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Set by `make feedback-done` once the rules were tuned for it (app/feedback_review.py).
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)


class LearnedPreference(Base):
    """What "Not for me" taught about this user (feedback/learning.py). RLS: private.

    kind: company (value: the company as named), location (a city key), field (a job family), level_min /
    level_max (a seniority level, 1-9). `label` is how the Profile page names it ("Jobs at Okta")."""

    __tablename__ = "learned_preferences"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    value: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)
    feedback_id: Mapped[UUID | None] = mapped_column(ForeignKey("job_feedback.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
