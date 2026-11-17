from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class InboundMessage(Base):
    """One received alert email (or pasted alert). RLS: private to its user."""

    __tablename__ = "inbound_messages"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    message_id: Mapped[str] = mapped_column(Text)  # RFC 822 Message-ID; dedupe key per user
    channel: Mapped[str] = mapped_column(String(8), default="email")  # email | paste
    sender: Mapped[str] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # accepted → parsed | unparsed | failed
    status: Mapped[str] = mapped_column(String(16), default="accepted")
    parser: Mapped[str | None] = mapped_column(Text)  # "linkedin_digest@1"
    alert_name: Mapped[str | None] = mapped_column(Text)
    cards_found: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    forwarding_code: Mapped[str | None] = mapped_column(Text)  # from a Gmail forwarding confirmation
    forwarding_link: Mapped[str | None] = mapped_column(Text)  # the same, in Gmail's newer link form
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ForwardSender(Base):
    """An address the user forwards alerts from by hand (Mail setup). Lowercased."""

    __tablename__ = "forward_senders"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    address: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InboundRaw(Base):
    """The raw email, kept for re-parsing after a parser fix and deleted after the retention period."""

    __tablename__ = "inbound_raw"
    inbound_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_messages.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    body: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
