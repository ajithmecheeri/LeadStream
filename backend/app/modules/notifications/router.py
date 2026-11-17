"""WhatsApp alerts (add and verify a number, turn job alerts on or off, send a test, see recent messages) and the
in-app bell."""

from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from sqlalchemy import select, update

from app.core.db import user_scope
from app.core.deps import User, UserDB
from app.core.errors import AppError, Conflict, NotFound
from app.modules.catalog.models import Job
from app.modules.jobs.models import UserJob
from app.modules.matching.models import JobMatch
from app.modules.notifications import bell, service, whatsapp
from app.modules.notifications.models import Notification
from app.modules.notifications.schemas import (
    BellItemOut,
    BellOut,
    CodeIn,
    NotificationOut,
    NumberIn,
    WhatsAppIn,
    WhatsAppOut,
)
from app.modules.settings.models import NotificationSettings

router = APIRouter(prefix="/notifications", tags=["notifications"])


async def _settings(db) -> NotificationSettings:
    ns = await db.scalar(select(NotificationSettings))
    if ns is None:
        raise NotFound("Notification settings")
    return ns


async def _out(db, ns: NotificationSettings, tz: str) -> WhatsAppOut:
    recent = await db.scalars(
        select(Notification)
        .where(Notification.channel == "whatsapp")
        .order_by(Notification.created_at.desc())
        .limit(20)
    )
    return WhatsAppOut(
        configured=whatsapp.configured(),
        number=whatsapp.masked(ns.whatsapp_number) if ns.whatsapp_number else None,
        verified=ns.whatsapp_verified_at is not None,
        code_sent=ns.whatsapp_code_hash is not None,
        jobs=ns.whatsapp_jobs,
        sent_today=await service.sent_today(db, tz, datetime.now(UTC)),
        daily_limit=ns.max_push_per_day,
        recent=[NotificationOut.model_validate(n) for n in recent],
    )


async def _deliver(db, ns: NotificationSettings, kind: str, body: str, send) -> Notification:
    """Send right away (codes and tests: the user is waiting) and keep a row of it. A failure undoes the request
    (the number isn't saved) and the user sees WhatsApp's reason."""
    try:
        sent = await send()
    except whatsapp.WhatsAppError as e:
        raise AppError(502, "whatsapp_failed", str(e)) from e
    n = Notification(
        user_id=ns.user_id,
        channel="whatsapp",
        kind=kind,
        body=body,
        attempts=1,
        status="sent" if sent.provider_id else "logged",
        provider_id=sent.provider_id,
        sent_at=datetime.now(UTC),
    )
    db.add(n)
    await db.flush()
    return n


@router.get("/whatsapp", response_model=WhatsAppOut)
async def get_whatsapp(user: User, db: UserDB):
    return await _out(db, await _settings(db), await service.user_timezone(db, user.id))


@router.post("/whatsapp/number", response_model=WhatsAppOut)
async def set_number(body: NumberIn, user: User, db: UserDB):
    """Save the number and send it a one-time code on WhatsApp. Alerts start once the code is entered."""
    number = whatsapp.normalise_number(body.number)
    if number is None:
        raise AppError(
            422,
            "validation_error",
            "Enter a mobile number with its country code",
            [{"field": "number", "message": "For example +91 98765 43210"}],
        )
    ns = await _settings(db)
    await _send_code(db, ns, number)
    return await _out(db, ns, await service.user_timezone(db, user.id))


@router.post("/whatsapp/code", response_model=WhatsAppOut)
async def send_code(user: User, db: UserDB):
    """Send a code to the number already saved (given at sign-up, or a new code after one expired)."""
    ns = await _settings(db)
    if not ns.whatsapp_number:
        raise Conflict("no_number", "Add a WhatsApp number first")
    if ns.whatsapp_verified_at:
        raise Conflict("already_verified", "This number is already verified")
    await _send_code(db, ns, ns.whatsapp_number)
    return await _out(db, ns, await service.user_timezone(db, user.id))


async def _send_code(db, ns: NotificationSettings, number: str) -> None:
    now = datetime.now(UTC)
    if ns.whatsapp_code_sent_at and now - ns.whatsapp_code_sent_at < service.CODE_RESEND_AFTER:
        raise AppError(429, "too_soon", "A code was sent a moment ago. Wait a minute before asking again.")
    code = service.new_code()
    ns.whatsapp_number, ns.whatsapp_verified_at = number, None
    ns.whatsapp_code_hash, ns.whatsapp_code_sent_at, ns.whatsapp_code_tries = (
        service.code_hash(ns.user_id, code),
        now,
        0,
    )
    await db.flush()
    await _deliver(db, ns, "code", "Verification code", lambda: whatsapp.send_code(number, code))


@router.post("/whatsapp/verify", response_model=WhatsAppOut)
async def verify(body: CodeIn, user: User, db: UserDB):
    ns = await _settings(db)
    if not ns.whatsapp_code_hash or not ns.whatsapp_code_sent_at:
        raise Conflict("no_code", "Ask for a code first")
    expired = datetime.now(UTC) - ns.whatsapp_code_sent_at > service.CODE_TTL
    if expired or ns.whatsapp_code_tries >= service.CODE_TRIES:
        raise Conflict("code_expired", "That code has expired. Ask for a new one.")
    if not service.code_matches(ns, body.code):
        # Counted in a transaction of its own: the error below rolls this request back.
        async with user_scope(user.id) as own:
            await own.execute(
                update(NotificationSettings).values(
                    whatsapp_code_tries=NotificationSettings.whatsapp_code_tries + 1
                )
            )
        raise AppError(
            422,
            "validation_error",
            "That code is not right",
            [{"field": "code", "message": "Check the code"}],
        )
    ns.whatsapp_verified_at, ns.whatsapp_code_hash, ns.whatsapp_code_tries = datetime.now(UTC), None, 0
    await db.flush()
    return await _out(db, ns, await service.user_timezone(db, user.id))


@router.patch("/whatsapp", response_model=WhatsAppOut)
async def set_whatsapp(body: WhatsAppIn, user: User, db: UserDB):
    ns = await _settings(db)
    ns.whatsapp_jobs = body.jobs
    await db.flush()
    return await _out(db, ns, await service.user_timezone(db, user.id))


@router.post("/whatsapp/test", response_model=NotificationOut)
async def send_test(user: User, db: UserDB):
    """Send your best open match now, as a job alert looks."""
    ns = await _settings(db)
    if not (ns.whatsapp_number and ns.whatsapp_verified_at):
        raise Conflict("not_verified", "Verify your WhatsApp number first")
    row = (
        await db.execute(
            select(UserJob, Job, JobMatch)
            .join(Job, Job.id == UserJob.job_id)
            .join(JobMatch, JobMatch.user_job_id == UserJob.id)
            .where(UserJob.status.in_(service.OPEN_STATUSES), JobMatch.band.in_(("strong", "good")))
            .order_by(JobMatch.score.desc(), UserJob.first_seen_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        raise Conflict("no_match", "No Top match to send yet")
    uj, job, match = row
    number = ns.whatsapp_number
    return await _deliver(
        db,
        ns,
        "test",
        service.job_line(job.title, job.company, match.score),
        lambda: whatsapp.send_job(number, job.title, job.company or "", match.score, service.job_link(uj.id)),
    )


@router.delete("/whatsapp", status_code=status.HTTP_204_NO_CONTENT)
async def remove_number(user: User, db: UserDB):
    """Forget the number; messages waiting to be sent are dropped."""
    ns = await _settings(db)
    ns.whatsapp_number = ns.whatsapp_verified_at = ns.whatsapp_code_hash = ns.whatsapp_code_sent_at = None
    ns.whatsapp_code_tries = 0
    await db.execute(
        update(Notification)
        .where(Notification.status.in_(("queued", "held")))
        .values(status="skipped", error="WhatsApp number removed")
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/bell", response_model=BellOut)
async def get_bell(user: User, db: UserDB):
    """What needs your attention: new top matches, possible duplicates, follow-ups due, jobs that may have expired."""
    ns = await _settings(db)
    found = await bell.items(db, user.id)
    unread = [ns.bell_seen_at is None or i.at > ns.bell_seen_at for i in found]
    return BellOut(
        items=[BellItemOut(**vars(i), unread=u) for i, u in zip(found, unread, strict=True)],
        unread=sum(unread),
    )


@router.post("/bell/seen", status_code=status.HTTP_204_NO_CONTENT)
async def bell_seen(user: User, db: UserDB):
    """You opened the bell: everything in it now counts as read."""
    ns = await _settings(db)
    ns.bell_seen_at = datetime.now(UTC)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
