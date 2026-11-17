"""Job alerts on WhatsApp (user, 2026-11-05: "WhatsApp alert for high match jobs").

After each scoring run, `alert_new_matches` queues one message per job that is:
- a strong match (at or above its search profile's threshold: the "Strong match" band);
- new to the user: first seen in the last 24 hours, not applied, ignored or expired (so a re-score after a weight
  change never alerts old jobs);
- not alerted before (one message per job, ever: a job repeated in a later alert email doesn't send again);
- not a duplicate: merged ones are status "duplicate", and a possible duplicate of a job already applied to waits
  for the user's answer on its page.

Messages wait out quiet hours (held until the quiet hours end, on the user's clock) and stop at the daily limit
(Settings: max alerts per day); the job is still in Top matches either way. The worker task sends them.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import get_settings
from app.core.worker import defer
from app.modules.applications.service import timezone as user_timezone
from app.modules.catalog.models import Job
from app.modules.jobs.models import JobDuplicate, UserJob
from app.modules.matching.models import JobMatch
from app.modules.notifications import whatsapp
from app.modules.notifications.models import Notification
from app.modules.settings.models import NotificationSettings

log = logging.getLogger("fitfirst.notifications")

SEND = "notifications.send"
ALERT_WINDOW = timedelta(hours=24)
OPEN_STATUSES = ("new", "seen")
# Toward the daily limit. Messages only written to the log ("logged", before WhatsApp was set up) count only
# while it still isn't, so they don't use up the first day of real sending (2026-11-06).
COUNTED = ("queued", "held", "sent", "logged")
CODE_TTL = timedelta(minutes=10)
CODE_RESEND_AFTER = timedelta(seconds=60)
CODE_TRIES = 5


def quiet_until(now: datetime, tz: str, start: time | None, end: time | None) -> datetime | None:
    """When the user's quiet hours end, if `now` falls inside them (they may run past midnight: 22:00–07:00)."""
    if start is None or end is None or start == end:
        return None
    zone = ZoneInfo(tz)
    local = now.astimezone(zone)
    t = local.time().replace(tzinfo=None)
    inside = start <= t < end if start < end else (t >= start or t < end)
    if not inside:
        return None
    ends = datetime.combine(local.date(), end, tzinfo=zone)
    if ends <= local:
        ends += timedelta(days=1)
    return ends.astimezone(UTC)


def job_link(user_job_id: UUID) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/jobs/{user_job_id}"


def job_line(title: str, company: str | None, score: int) -> str:
    return f"Top match, {score}%: {title} at {company or 'a company'}."


async def sent_today(db: AsyncSession, tz: str, now: datetime) -> int:
    midnight = datetime.combine(now.astimezone(ZoneInfo(tz)).date(), time(0), tzinfo=ZoneInfo(tz))
    counted = [s for s in COUNTED if s != "logged"] if whatsapp.configured() else COUNTED
    return (
        await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.kind == "new_job",
                Notification.status.in_(counted),
                Notification.created_at >= midnight,
            )
        )
        or 0
    )


def _maybe_applied_already():
    """Possibly the same role as a job the user already applied to (an open duplicate pair): no alert."""
    other = aliased(UserJob)
    return (
        select(JobDuplicate.id)
        .join(
            other,
            or_(
                (JobDuplicate.user_job_id == UserJob.id) & (other.id == JobDuplicate.other_id),
                (JobDuplicate.other_id == UserJob.id) & (other.id == JobDuplicate.user_job_id),
            ),
        )
        .where(JobDuplicate.answer.is_(None), other.status == "applied")
        .exists()
    )


async def queue_send(user_id: UUID, notification_id: UUID, at: datetime | None = None) -> None:
    now = datetime.now(UTC)
    delay = max(3, int((at - now).total_seconds())) if at else 3  # lets the caller's transaction commit first
    try:
        await defer(
            SEND,
            queueing_lock=f"notify:{notification_id}",
            schedule_in_seconds=delay,
            user_id=str(user_id),
            notification_id=str(notification_id),
        )
    except AlreadyEnqueued:
        pass


async def alert_new_matches(
    db: AsyncSession, user_id: UUID, user_job_ids: list[UUID], now: datetime | None = None
) -> int:
    """Queue WhatsApp alerts for the strong, new matches among these jobs. Returns how many were queued."""
    ns = await db.get(NotificationSettings, user_id)
    if ns is None or not (ns.whatsapp_number and ns.whatsapp_verified_at and ns.whatsapp_jobs):
        return 0
    now = now or datetime.now(UTC)
    rows = (
        await db.execute(
            select(UserJob, Job, JobMatch)
            .join(Job, Job.id == UserJob.job_id)
            .join(JobMatch, JobMatch.user_job_id == UserJob.id)
            .where(
                UserJob.id.in_(user_job_ids),
                JobMatch.band == "strong",
                UserJob.status.in_(OPEN_STATUSES),
                UserJob.first_seen_at >= now - ALERT_WINDOW,
                ~select(Notification.id)
                .where(Notification.user_job_id == UserJob.id, Notification.kind == "new_job")
                .exists(),
                ~_maybe_applied_already(),
            )
            .order_by(JobMatch.score.desc())
        )
    ).all()
    if not rows:
        return 0
    tz = await user_timezone(db, user_id)
    held_until = quiet_until(now, tz, ns.quiet_start, ns.quiet_end)
    room = max(0, ns.max_push_per_day - await sent_today(db, tz, now))
    queued = 0
    for uj, job, match in rows:
        over = queued >= room
        values = {
            "user_id": user_id,
            "user_job_id": uj.id,
            "channel": "whatsapp",
            "kind": "new_job",
            "status": "skipped" if over else ("held" if held_until else "queued"),
            "body": job_line(job.title, job.company, match.score),
            "send_after": held_until or now,
            "error": f"Daily limit reached ({ns.max_push_per_day} a day)" if over else None,
        }
        new_id = await db.scalar(
            insert(Notification)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=["user_id", "user_job_id", "channel"],
                # Literal SQL, not a bound parameter: Postgres matches the partial unique index only while it
                # plans with the value; after five runs a long-lived worker switches to a generic plan and the
                # insert failed ("no unique or exclusion constraint matching"), losing the rescore with it
                # (2026-11-12).
                index_where=text("kind = 'new_job'"),
            )
            .returning(Notification.id)
        )
        if new_id is not None and not over:
            await queue_send(user_id, new_id, held_until)
            queued += 1
    if queued:
        log.info("queued %d WhatsApp alerts for user %s", queued, user_id)
    return queued


def code_hash(user_id: UUID, code: str) -> str:
    return hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()


def new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def code_matches(ns: NotificationSettings, code: str) -> bool:
    return bool(ns.whatsapp_code_hash) and hmac.compare_digest(
        ns.whatsapp_code_hash, code_hash(ns.user_id, code.strip())
    )
