from datetime import datetime, time
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, Text, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NotificationSettings(Base):
    __tablename__ = "notification_settings"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    push: Mapped[bool] = mapped_column(Boolean, default=True)
    email: Mapped[bool] = mapped_column(Boolean, default=True)
    quiet_start: Mapped[time | None] = mapped_column(Time, default=time(22, 0))
    quiet_end: Mapped[time | None] = mapped_column(Time, default=time(7, 0))
    max_push_per_day: Mapped[int] = mapped_column(Integer, default=10)  # job alerts a day, every channel
    digest_time: Mapped[time] = mapped_column(Time, default=time(19, 0))
    network_daily_cap: Mapped[int] = mapped_column(Integer, default=5)
    network_weekly_limit: Mapped[int] = mapped_column(Integer, default=100)
    # WhatsApp (milestone 6): digits with the country code ("919876543210"), verified by a one-time code.
    whatsapp_number: Mapped[str | None] = mapped_column(Text)
    whatsapp_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    whatsapp_jobs: Mapped[bool] = mapped_column(Boolean, default=True)  # strong matches on WhatsApp
    whatsapp_code_hash: Mapped[str | None] = mapped_column(Text)  # sha256 of the code; cleared once used
    whatsapp_code_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    whatsapp_code_tries: Mapped[int] = mapped_column(SmallInteger, default=0)
    bell_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )  # last opened the bell (6.2)
