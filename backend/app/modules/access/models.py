from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Invite(Base):
    """An invite the super admin made: a role and, for a job seeker, free months (a coupon). No row level security:
    only the super admin's routes and the link's holder (by its token) read it. Only the token's hash is kept."""

    __tablename__ = "invites"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)  # job_seeker | admin
    free_months: Mapped[int] = mapped_column(Integer, default=0)  # 0, 1 or 3
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Subscription(Base):
    """One paid or coupon period of a job seeker (private, RLS). users.access_until holds the latest end."""

    __tablename__ = "subscriptions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)  # coupon | payment
    plan: Mapped[str] = mapped_column(Text)  # 1m | 3m | 6m | 12m
    months: Mapped[int] = mapped_column(Integer)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    invite_id: Mapped[UUID | None] = mapped_column(ForeignKey("invites.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
