from datetime import datetime
from uuid import UUID

from sqlalchemy import ARRAY, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ApplyProfile(Base):
    """What application forms ask for beyond the candidate profile (milestone 14.1). One per user. RLS: private.

    languages, work_history and education are lists validated by apply/schemas.py."""

    __tablename__ = "apply_profiles"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    phone: Mapped[str | None] = mapped_column(Text)
    address_line1: Mapped[str | None] = mapped_column(Text)
    address_line2: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    postal_code: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    websites: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    languages: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    work_history: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    education: Mapped[list[dict]] = mapped_column(JSONB, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
