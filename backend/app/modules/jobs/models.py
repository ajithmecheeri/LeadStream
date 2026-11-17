from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.core.db import Base
from app.core.vector import Embedding

# A recruiter invite outranks an alert, which outranks a recommendation or a feed listing, when one job arrives
# several ways.
LEAD_RANK = {"job_board": 0, "company_feed": 0, "recommendation": 0, "alert": 1, "recruiter_invite": 2}


class UserJob(Base):
    """A catalog job as one user received it. RLS: private. Holds everything user-specific about the job."""

    __tablename__ = "user_jobs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    inbound_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inbound_messages.id", ondelete="SET NULL")
    )
    # new | seen | ignored | applied | expired | duplicate (merged into `duplicate_of`; see jobs/duplicates.py)
    status: Mapped[str] = mapped_column(String(16), default="new")
    duplicate_of: Mapped[UUID | None] = mapped_column(ForeignKey("user_jobs.id", ondelete="SET NULL"))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_by: Mapped[str | None] = mapped_column(Text)  # user | auto (see jobs/expiry.py)
    # The user checked the posting and said it's still open: the expiry clock restarts from here.
    confirmed_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lead: Mapped[str] = mapped_column(
        String(24)
    )  # alert | recommendation | recruiter_invite | company_feed | job_board
    outside_preference: Mapped[bool] = mapped_column(Boolean, default=False)
    # Naukri recruiter invites: the apply link carries the user's login token, so it lives here only.
    apply_url: Mapped[str | None] = mapped_column(Text)
    card_details: Mapped[dict] = mapped_column(JSONB, default=dict)  # "2 connections" is about this user
    # A full description the user pasted: theirs only, it never changes the shared catalog.
    description: Mapped[str | None] = mapped_column(Text)
    description_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Voyage embedding of the job as this user sees it, and the hash of that text (re-embed when it changes).
    embedding: Mapped[list[float] | None] = deferred(mapped_column(Embedding))
    embedding_key: Mapped[str | None] = mapped_column(Text)
    # Blockers the user accepted for this job (e.g. "gap:skills"): readiness stops counting them.
    acknowledged: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class JobDuplicate(Base):
    """Two of the user's jobs that are, or may be, one role (see jobs/duplicates.py). RLS: private.

    `user_job_id` is the later of the two. `answer` is the user's: same (merged) or different (never asked
    again)."""

    __tablename__ = "job_duplicates"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user_job_id: Mapped[UUID] = mapped_column(ForeignKey("user_jobs.id", ondelete="CASCADE"))
    other_id: Mapped[UUID] = mapped_column(ForeignKey("user_jobs.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)  # same | likely | agency
    reason: Mapped[str] = mapped_column(Text)
    similarity: Mapped[int | None] = mapped_column(Integer)  # descriptions, % alike (None: one is missing)
    answer: Mapped[str | None] = mapped_column(Text)  # same | different
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
