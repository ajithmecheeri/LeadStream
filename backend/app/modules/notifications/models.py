from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, SmallInteger, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Notification(Base):
    """One message to the user (the outbox). RLS: private.

    status: queued → sent | logged (no WhatsApp keys: written to the worker log) | failed; held (quiet hours,
    sent at `send_after`); skipped (not sent, `error` says why: daily limit, number removed…).
    """

    __tablename__ = "notifications"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    user_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_jobs.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(Text, default="whatsapp")
    kind: Mapped[str] = mapped_column(Text)  # new_job | test | code
    status: Mapped[str] = mapped_column(Text, default="queued")
    body: Mapped[str] = mapped_column(Text)  # what the message says, as shown in the app
    send_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)
    provider_id: Mapped[str | None] = mapped_column(Text)  # WhatsApp's message id
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
