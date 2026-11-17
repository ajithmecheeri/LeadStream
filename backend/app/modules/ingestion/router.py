"""Received alert emails: the internal endpoint the email worker calls, and the user's mail and inbox views."""

import base64
import binascii
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, or_, select

from app.core.config import get_settings
from app.core.deps import User, UserDB
from app.core.errors import AppError, Conflict, NotFound
from app.core.security import new_inbound_token
from app.modules.auth.service import forwarding_address
from app.modules.catalog.parsers.base import sender
from app.modules.catalog.parsers.registry import load
from app.modules.ingestion.models import ForwardSender, InboundMessage
from app.modules.ingestion.schemas import (
    DkimResult,
    ForwardSenderIn,
    ForwardSenderOut,
    InboundIn,
    InboundResult,
    InboxMessageOut,
    MailOut,
    UploadIn,
)
from app.modules.ingestion.service import (
    GOOGLE_FORWARDING,
    accept_inbound,
    forward_senders,
    is_portal,
    verify_signature,
)
from app.modules.users.models import AuditEvent
from app.modules.users.models import User as UserRow

# Mounted outside /api, so Caddy never exposes it to browsers; only the email worker calls it.
internal_router = APIRouter(prefix="/internal", tags=["internal"], include_in_schema=False)
router = APIRouter(tags=["mail"])


@internal_router.post("/inbound", response_model=InboundResult)
async def inbound(
    request: Request,
    x_signature: Annotated[str | None, Header()] = None,
    x_timestamp: Annotated[str | None, Header()] = None,
):
    # Base64 adds a third; allow for that plus the JSON envelope before reading the body.
    limit = get_settings().inbound_max_bytes * 4 // 3 + 64_000
    if int(request.headers.get("content-length") or 0) > limit:
        raise AppError(413, "too_large", "Email is too large")
    body = await request.body()
    if len(body) > limit:
        raise AppError(413, "too_large", "Email is too large")
    verify_signature(body, x_signature, x_timestamp)
    try:
        payload = InboundIn.model_validate_json(body)
    except ValidationError as e:
        raise AppError(422, "validation_error", "Invalid inbound payload", e.errors(include_url=False)) from e

    result = await accept_inbound(payload)
    # 202 when stored and queued; 200 with a reason when deliberately dropped (the worker must not retry).
    return JSONResponse(result.model_dump(mode="json"), status_code=202 if result.accepted else 200)


@router.get("/mail", response_model=MailOut)
async def mail(user: User, db: UserDB):
    row = await db.get(UserRow, user.id)
    last = await db.scalar(select(func.max(InboundMessage.received_at)))
    code = (
        await db.execute(
            select(InboundMessage.forwarding_code, InboundMessage.forwarding_link, InboundMessage.received_at)
            .where(
                or_(InboundMessage.forwarding_code.is_not(None), InboundMessage.forwarding_link.is_not(None))
            )
            .order_by(InboundMessage.received_at.desc())
            .limit(1)
        )
    ).first()
    senders = await db.scalars(select(ForwardSender).order_by(ForwardSender.created_at))
    return MailOut(
        address=forwarding_address(row),
        forward_senders=[ForwardSenderOut.model_validate(s) for s in senders],
        receiving=last is not None,
        last_received_at=last,
        forwarding_code=code[0] if code else None,
        forwarding_link=code[1] if code else None,
        forwarding_code_at=code[2] if code else None,
        upload_enabled=get_settings().env == "local",
    )


@router.post("/mail/address/rotate", response_model=MailOut)
async def rotate_address(user: User, db: UserDB):
    """A new forwarding address. Mail to the old one is rejected from now on; update the Gmail filter."""
    row = await db.get(UserRow, user.id, with_for_update=True)
    row.inbound_token = new_inbound_token()
    db.add(AuditEvent(user_id=user.id, actor="user", event="mail_address_rotated", entity="user"))
    await db.flush()
    return await mail(user, db)


MAX_FORWARD_SENDERS = 3


@router.post("/mail/senders", response_model=ForwardSenderOut, status_code=201)
async def add_forward_sender(body: ForwardSenderIn, user: User, db: UserDB):
    """Accept alerts this user forwards by hand from `address` (DKIM must pass for its domain on arrival)."""
    address = str(body.address).lower()
    domain = address.rpartition("@")[2]
    if is_portal(address) or address == GOOGLE_FORWARDING or domain == get_settings().inbound_domain.lower():
        raise AppError(422, "not_your_address", "Use the email address you forward from, not a job portal's")
    existing = await forward_senders(db)
    if address in existing:
        raise Conflict("already_added", f"{address} is already on the list")
    if len(existing) >= MAX_FORWARD_SENDERS:
        raise AppError(422, "too_many", f"You can forward from up to {MAX_FORWARD_SENDERS} addresses")
    row = ForwardSender(user_id=user.id, address=address)
    db.add(row)
    db.add(AuditEvent(user_id=user.id, actor="user", event="forward_sender_added", entity="forward_sender"))
    await db.flush()
    await db.refresh(row)
    return row


@router.delete("/mail/senders/{sender_id}", status_code=204)
async def remove_forward_sender(sender_id: UUID, user: User, db: UserDB):
    row = await db.get(ForwardSender, sender_id)
    if row is None:
        raise NotFound("Address")
    await db.delete(row)
    db.add(AuditEvent(user_id=user.id, actor="user", event="forward_sender_removed", entity="forward_sender"))
    return Response(status_code=204)


@router.get("/inbox/messages", response_model=list[InboxMessageOut])
async def inbox_messages(
    _: User,
    db: UserDB,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[datetime | None, Query(description="Return messages received before this time")] = None,
):
    q = select(InboundMessage).order_by(InboundMessage.received_at.desc()).limit(limit)
    if before is not None:
        q = q.where(InboundMessage.received_at < before)
    return (await db.execute(q)).scalars().all()


_UPLOAD_REJECTED = {
    "duplicate": "This email has already been received",
    "sender_not_allowed": "Only LinkedIn and Naukri alert emails (or Gmail's forwarding confirmation) are "
    "accepted, or alerts forwarded from an address on Mail setup",
    "too_large": "Email is too large",
    "unreadable": "This file isn't a readable email (.eml)",
    "unknown_recipient": "Your account can't receive email right now",
}


@router.post("/inbox/upload", response_model=InboundResult, status_code=202)
async def upload_email(body: UploadIn, user: User, db: UserDB):
    """Deliver a saved alert email (.eml) as if it had been forwarded. Local development only: an uploaded
    file has no verified DKIM signature, so in production it could plant fake listings in the shared catalog.
    """
    if get_settings().env != "local":
        raise NotFound()
    try:
        raw = base64.b64decode(body.raw_mime_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise AppError(422, "unreadable", _UPLOAD_REJECTED["unreadable"]) from e
    from_domain = sender(load(raw)).rpartition("@")[2]
    address = forwarding_address(await db.get(UserRow, user.id))
    payload = InboundIn(
        recipient=address,
        # Stand-in for the email worker's DKIM check, which a file from disk can't have.
        dkim=[DkimResult(domain=from_domain or "unknown", result="pass")],
        raw_mime_base64=body.raw_mime_base64,
    )
    result = await accept_inbound(payload, channel="paste")
    if not result.accepted:
        raise AppError(
            422, result.reason or "rejected", _UPLOAD_REJECTED.get(result.reason or "", "Rejected")
        )
    return result
