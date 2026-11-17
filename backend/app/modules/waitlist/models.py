from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class WaitlistEntry(Base):
    """Someone who left their email on the home page. Shared: no user_id, no RLS (they have no account)."""

    __tablename__ = "waitlist"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, default="home")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContactMessage(Base):
    """A message from the public contact page. Shared: no user_id, no RLS; only the super admin reads them."""

    __tablename__ = "contact_messages"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(Text)  # general | support | privacy | feedback
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
