from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class NotificationOut(BaseModel):
    model_config = {"from_attributes": True}
    id: UUID
    user_job_id: UUID | None
    kind: str  # new_job | test | code
    status: str  # queued | held | sent | logged | failed | skipped
    body: str
    send_after: datetime
    error: str | None
    created_at: datetime
    sent_at: datetime | None


class WhatsAppOut(BaseModel):
    configured: bool  # WhatsApp keys are set; otherwise messages go to the worker log
    number: str | None  # masked: "+91 ••••• 43210"
    verified: bool
    code_sent: bool  # a code is waiting to be entered
    jobs: bool  # strong matches on WhatsApp
    sent_today: int
    daily_limit: int
    recent: list[NotificationOut]


class NumberIn(BaseModel):
    number: str = Field(min_length=10, max_length=20)  # "+91 98765 43210" or a 10-digit Indian mobile


class CodeIn(BaseModel):
    code: str = Field(pattern=r"^\s*\d{6}\s*$")


class WhatsAppIn(BaseModel):
    jobs: bool


class BellItemOut(BaseModel):
    model_config = {"from_attributes": True}
    key: str
    kind: Literal["strong", "duplicate", "follow_up", "expiry"]
    title: str
    detail: str
    user_job_id: UUID
    at: datetime
    unread: bool


class BellOut(BaseModel):
    items: list[BellItemOut]
    unread: int = Field(description="Items newer than the last time the bell was opened")
