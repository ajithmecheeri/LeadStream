from datetime import datetime
from uuid import UUID

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class JobMatch(Base):
    """How well one of the user's jobs fits them. RLS: private. One row per user job, rewritten on re-score.

    `band` decides the Jobs tab: strong and good are Top matches; low and filtered are Other jobs.
    `ranking` scores every resume in the library: [{resume_id, label, score, reason}], best first.
    """

    __tablename__ = "job_matches"
    user_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    search_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("search_profiles.id", ondelete="SET NULL")
    )
    band: Mapped[str] = mapped_column(Text)  # strong | good | low | filtered
    score: Mapped[int] = mapped_column(SmallInteger)
    filter_reason: Mapped[str | None] = mapped_column(Text)
    factors: Mapped[dict] = mapped_column(JSONB, default=dict)  # factor -> 0-100, for the best resume
    # Why the best resume isn't at 100: {"lost": {factor|similarity|clash: points}, "skills_have": [...],
    # "skills_missing": [...]}. Empty for rows scored before migration 0007 until they are re-scored.
    explain: Mapped[dict] = mapped_column(JSONB, default=dict)
    ranking: Mapped[list] = mapped_column(JSONB, default=list)
    primary_resume_id: Mapped[UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    primary_score: Mapped[int | None] = mapped_column(SmallInteger)
    best_resume_id: Mapped[UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    best_score: Mapped[int | None] = mapped_column(SmallInteger)
    cover_letter_id: Mapped[UUID | None] = mapped_column(ForeignKey("cover_letters.id", ondelete="SET NULL"))
    strengths: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    gaps: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    method: Mapped[str] = mapped_column(Text, default="rules")  # rules | llm
    provisional: Mapped[bool] = mapped_column(Boolean, default=True)  # scored from the alert's few facts
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
