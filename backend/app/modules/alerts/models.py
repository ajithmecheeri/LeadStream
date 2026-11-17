from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AlertFeed(Base):
    """A Google Alerts RSS feed the user added (discovery plan decision 10), and what its last read brought.
    RLS: private (the feed link is personal)."""

    __tablename__ = "alert_feeds"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    feed_url: Mapped[str] = mapped_column(Text)
    query: Mapped[str | None] = mapped_column(Text)  # the alert's search, from the feed's title
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_found: Mapped[int] = mapped_column(Integer, default=0)  # job pages in the feed
    last_added: Mapped[int] = mapped_column(Integer, default=0)  # new to the user
    last_skipped: Mapped[int] = mapped_column(Integer, default=0)  # links to other sites
    last_job_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PgUUID(as_uuid=True)), default=list)  # user_jobs
