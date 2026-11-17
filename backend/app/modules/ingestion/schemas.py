from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class DkimResult(BaseModel):
    domain: str
    result: str  # "pass" | "fail" | "none" | …, as the receiving mail server reported it


class InboundIn(BaseModel):
    """What the Cloudflare Email Worker (or `make inbound`) posts for each email it receives."""

    recipient: str
    envelope_from: str = ""
    message_id: str | None = None
    received_at: datetime | None = None
    dkim: list[DkimResult] = Field(default_factory=list)
    raw_mime_base64: str


RejectReason = Literal["unknown_recipient", "sender_not_allowed", "duplicate", "too_large", "unreadable"]


class InboundResult(BaseModel):
    accepted: bool
    inbound_message_id: UUID | None = None
    reason: RejectReason | None = None


class ForwardSenderOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    address: str
    created_at: datetime


class ForwardSenderIn(BaseModel):
    address: EmailStr = Field(max_length=254)


class MailOut(BaseModel):
    address: str
    # Addresses the user forwards alerts from by hand (when a Gmail filter isn't possible).
    forward_senders: list[ForwardSenderOut] = Field(default_factory=list)
    # True once any email has arrived from Google's forwarding service or a job portal.
    receiving: bool
    last_received_at: datetime | None
    forwarding_code: str | None  # latest Gmail forwarding-confirmation code, to type into Gmail
    forwarding_link: str | None  # or the link to open instead (Gmail's newer confirmation)
    forwarding_code_at: datetime | None
    # Local development only: POST /inbox/upload delivers a saved .eml file.
    upload_enabled: bool = False


class InboxMessageOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    received_at: datetime
    channel: str
    sender: str
    subject: str | None
    status: str
    parser: str | None
    alert_name: str | None
    cards_found: int | None
    error: str | None


class UploadIn(BaseModel):
    """A saved alert email (.eml), for testing parsers locally. Only available when ENV=local."""

    raw_mime_base64: str
