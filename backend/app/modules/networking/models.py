from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ConnectionImport(Base):
    """One upload of the user's LinkedIn connections export. Private. The file itself isn't kept."""

    __tablename__ = "connection_imports"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    file_name: Mapped[str | None] = mapped_column(Text)
    total: Mapped[int] = mapped_column(Integer, default=0)
    added: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    kept_email: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Connection(Base):
    """A 1st-degree LinkedIn connection, from the user's own export. Private."""

    __tablename__ = "connections"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    person_key: Mapped[str] = mapped_column(Text)  # profile URL, or name + company (see importer.py)
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    profile_url: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    position: Mapped[str | None] = mapped_column(Text)
    connected_on: Mapped[date | None] = mapped_column(Date)
    company_key: Mapped[str | None] = mapped_column(Text)
    import_id: Mapped[UUID | None] = mapped_column(ForeignKey("connection_imports.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    @property
    def name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p)


class Outreach(Base):
    """Someone the user contacted on LinkedIn themselves. Private. Stage: sent → accepted → conversation →
    referral → closed."""

    __tablename__ = "outreach"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)  # warm | target | manual
    person_name: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    company: Mapped[str | None] = mapped_column(Text)
    profile_url: Mapped[str | None] = mapped_column(Text)
    connection_id: Mapped[UUID | None] = mapped_column(ForeignKey("connections.id", ondelete="SET NULL"))
    user_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_jobs.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text, default="sent")
    stage_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    followed_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OutreachEvent(Base):
    __tablename__ = "outreach_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    outreach_id: Mapped[UUID] = mapped_column(ForeignKey("outreach.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)  # sent | stage | followed_up | note
    stage: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Suggestion(Base):
    """One of the day's suggestions: warm (a connection at a matching company), target (someone to find
    there) or followup (an outreach with no reply). Private. `payload` holds what the card shows."""

    __tablename__ = "network_suggestions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(Text)
    person_key: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(SmallInteger, default=0)
    connection_id: Mapped[UUID | None] = mapped_column(ForeignKey("connections.id", ondelete="CASCADE"))
    user_job_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_jobs.id", ondelete="CASCADE"))
    outreach_id: Mapped[UUID | None] = mapped_column(ForeignKey("outreach.id", ondelete="CASCADE"))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(Text, default="open")  # open | done | skipped
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
