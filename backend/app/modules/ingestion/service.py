"""Receiving alert emails: check the signature, the recipient and the sender, store, and queue parsing.

The Cloudflare Email Worker (or `make inbound` locally) posts each email with an HMAC over
`<timestamp>.<body>` using INBOUND_HMAC_SECRET. The API trusts the worker's DKIM verdicts because the
request is signed. An email is accepted only for an active user's forwarding address, and only from an
allowed sender whose domain passed DKIM: job-portal alerts, Google's forwarding confirmation, and the
addresses the user forwards alerts from by hand (their `forward_senders`, set on Mail setup).
"""

import base64
import binascii
import hashlib
import hmac
import logging
import re
import time
from email.message import EmailMessage
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import sessionmaker, user_scope
from app.core.errors import AppError
from app.core.worker import defer
from app.modules.catalog.parsers.base import sender, text_body
from app.modules.catalog.parsers.registry import load
from app.modules.ingestion.models import ForwardSender, InboundMessage, InboundRaw
from app.modules.ingestion.schemas import InboundIn, InboundResult
from app.modules.users.models import User

log = logging.getLogger("fitfirst.ingestion")

PARSE_ALERT = "ingestion.parse_alert"
SIGNATURE_MAX_AGE_SECONDS = 300
# Sender domains whose mail is accepted (with DKIM passing for that domain). Parsers then decide what
# each email is; anything they don't recognise is kept as 'unparsed' so the user can see it arrived.
ALERT_DOMAINS = ("linkedin.com", "naukri.com")
GOOGLE_FORWARDING = "forwarding-noreply@google.com"
_RECIPIENT = re.compile(r"^alerts-([A-Za-z0-9_-]+)@(.+)$")
_FORWARDING_CODE = re.compile(r"\(#(\d{6,})\)")
# Gmail's newer confirmation has no code, only a link to open; "vf-" confirms (the other link cancels).
_FORWARDING_LINK = re.compile(r"https://mail-settings\.google\.com/mail/vf-[A-Za-z0-9._~%/+=-]+")


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """The X-Signature value for a request body. Also used by `make inbound` and the tests."""
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify_signature(body: bytes, signature: str | None, timestamp: str | None) -> None:
    secret = get_settings().inbound_hmac_secret
    if not secret:
        raise AppError(503, "inbound_disabled", "Inbound email is not configured (INBOUND_HMAC_SECRET)")
    if not signature or not timestamp or not timestamp.isdigit():
        raise AppError(401, "bad_signature", "Missing or malformed signature")
    if abs(time.time() - int(timestamp)) > SIGNATURE_MAX_AGE_SECONDS:
        raise AppError(401, "bad_signature", "Signature timestamp is too old or in the future")
    if not hmac.compare_digest(sign(secret, timestamp, body), signature):
        raise AppError(401, "bad_signature", "Signature does not match")


def _domain_passed_dkim(domain: str, payload: InboundIn) -> bool:
    """A DKIM pass for the sender's domain or a parent of it (d=linkedin.com signs mail from e.linkedin.com)."""
    return any(
        d.result.lower() == "pass" and (domain == d.domain.lower() or domain.endswith("." + d.domain.lower()))
        for d in payload.dkim
    )


def is_portal(address: str) -> bool:
    domain = address.rpartition("@")[2]
    return any(domain == d or domain.endswith("." + d) for d in ALERT_DOMAINS)


def sender_allowed(from_addr: str, payload: InboundIn, forwards_from: frozenset[str] = frozenset()) -> bool:
    domain = from_addr.rpartition("@")[2]
    if from_addr == GOOGLE_FORWARDING:
        return _domain_passed_dkim("google.com", payload)
    if from_addr in forwards_from:
        return _domain_passed_dkim(domain, payload)
    return is_portal(from_addr) and _domain_passed_dkim(domain, payload)


async def forward_senders(db: AsyncSession) -> frozenset[str]:
    """The addresses this user forwards alerts from by hand. Run inside the user's scope."""
    return frozenset(await db.scalars(select(ForwardSender.address)))


def forwarding_code(from_addr: str, subject: str) -> str | None:
    """Gmail's "(#123456789) Gmail Forwarding Confirmation - Receive Mail from …" carries the code."""
    if from_addr != GOOGLE_FORWARDING:
        return None
    m = _FORWARDING_CODE.search(subject)
    return m.group(1) if m else None


def forwarding_link(from_addr: str, msg: EmailMessage) -> str | None:
    """The "click the link below to confirm the request" link in Gmail's newer confirmation email."""
    if from_addr != GOOGLE_FORWARDING:
        return None
    m = _FORWARDING_LINK.search(text_body(msg))
    return m.group(0) if m else None


async def _recipient_user_id(recipient: str) -> UUID | None:
    m = _RECIPIENT.match(recipient.strip().lower())
    if not m or m.group(2) != get_settings().inbound_domain.lower():
        return None
    # users has no RLS (like sign-in, which looks users up by email).
    async with sessionmaker()() as db:
        return await db.scalar(
            select(User.id).where(User.inbound_token == m.group(1), User.status == "active")
        )


async def accept_inbound(payload: InboundIn, channel: str = "email") -> InboundResult:
    user_id = await _recipient_user_id(payload.recipient)
    if user_id is None:
        return InboundResult(accepted=False, reason="unknown_recipient")
    try:
        raw = base64.b64decode(payload.raw_mime_base64, validate=True)
    except (binascii.Error, ValueError):
        return InboundResult(accepted=False, reason="unreadable")
    if len(raw) > get_settings().inbound_max_bytes:
        return InboundResult(accepted=False, reason="too_large")

    msg = load(raw)
    from_addr = sender(msg)
    async with user_scope(user_id) as db:
        forwards_from = await forward_senders(db)
    if not sender_allowed(from_addr, payload, forwards_from):
        log.info("inbound rejected: sender %s not allowed for user %s", from_addr, user_id)
        return InboundResult(accepted=False, reason="sender_not_allowed")

    subject = str(msg.get("Subject", "") or "")
    message_id = (payload.message_id or str(msg.get("Message-ID", "") or "")).strip()
    message_id = message_id or "sha256:" + hashlib.sha256(raw).hexdigest()
    code = forwarding_code(from_addr, subject)
    link = None if code else forwarding_link(from_addr, msg)

    async with user_scope(user_id) as db:
        values = dict(
            user_id=user_id, message_id=message_id, channel=channel, sender=from_addr, subject=subject or None
        )
        if payload.received_at:
            values["received_at"] = payload.received_at
        if code or link:
            values.update(
                forwarding_code=code,
                forwarding_link=link,
                status="parsed",
                parser="gmail_forwarding@2",
                cards_found=0,
            )
        new_id = await db.scalar(
            insert(InboundMessage).values(**values).on_conflict_do_nothing().returning(InboundMessage.id)
        )
        if new_id is None:
            return InboundResult(accepted=False, reason="duplicate")
        db.add(InboundRaw(inbound_message_id=new_id, user_id=user_id, body=raw))

    if not (code or link):
        await queue_parse(new_id, user_id)
    return InboundResult(accepted=True, inbound_message_id=new_id)


async def queue_parse(inbound_message_id: UUID, user_id: UUID) -> None:
    """Queue parsing after the message is committed. If queueing fails the message stays 'accepted' and
    the periodic sweep queues it again, so nothing is lost."""
    try:
        await defer(PARSE_ALERT, inbound_message_id=str(inbound_message_id), user_id=str(user_id))
    except Exception:
        log.exception("could not queue %s for inbound message %s", PARSE_ALERT, inbound_message_id)
