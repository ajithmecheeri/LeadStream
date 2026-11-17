from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ExtensionToken(Base):
    """A paired browser extension (milestone 14.3). RLS: private.

    Pending: `pair_code_hash` and `pair_expires_at` set, no token yet. Paired: `token_hash` set, the code cleared.
    Revoked: `revoked_at` set. Only sha256 hashes are stored."""

    __tablename__ = "extension_tokens"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str | None] = mapped_column(Text)  # "Chrome on Windows", as the extension reports it
    pair_code_hash: Mapped[str | None] = mapped_column(Text)
    pair_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
