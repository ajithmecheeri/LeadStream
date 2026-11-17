from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, LargeBinary, Text, func
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.core.db import Base
from app.core.vector import Embedding


class StoredFile(Base):
    """An original upload, kept so the user can download exactly what they gave us. RLS: private."""

    __tablename__ = "stored_files"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)  # pdf | docx | odt | rtf | txt | md
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(Text)
    data: Mapped[bytes] = deferred(mapped_column(LargeBinary))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Resume(Base):
    """One resume in the user's library: one primary and up to three variations. RLS: private."""

    __tablename__ = "resumes"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    search_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("search_profiles.id", ondelete="SET NULL")
    )
    label: Mapped[str] = mapped_column(Text)
    focus_tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    text: Mapped[str] = mapped_column(Text)
    file_id: Mapped[UUID | None] = mapped_column(ForeignKey("stored_files.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(Text, default="upload")  # upload | paste | tailored
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    embedding: Mapped[list[float] | None] = deferred(mapped_column(Embedding))
    embedding_key: Mapped[str | None] = mapped_column(Text)  # sha256 of the text the embedding was made from
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CoverLetter(Base):
    """A cover letter the user keeps as a base (up to five, one default). RLS: private."""

    __tablename__ = "cover_letters"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    file_id: Mapped[UUID | None] = mapped_column(ForeignKey("stored_files.id", ondelete="SET NULL"))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    embedding: Mapped[list[float] | None] = deferred(mapped_column(Embedding))
    embedding_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
