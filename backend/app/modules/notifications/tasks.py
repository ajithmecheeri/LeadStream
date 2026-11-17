"""Worker task: send one queued WhatsApp message (see service.alert_new_matches)."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.core.db import user_scope
from app.core.worker import app
from app.modules.catalog.models import Job
from app.modules.jobs.models import UserJob
from app.modules.matching.models import JobMatch
from app.modules.notifications import whatsapp
from app.modules.notifications.models import Notification
from app.modules.notifications.service import OPEN_STATUSES, SEND, job_line, job_link, queue_send
from app.modules.settings.models import NotificationSettings

log = logging.getLogger("fitfirst.notifications")

MAX_ATTEMPTS = 3


async def send(user_id: UUID, notification_id: UUID) -> str | None:
    """Send it now, or say why not. Returns the new status."""
    retry_at = None
    async with user_scope(user_id) as db:
        n = await db.get(Notification, notification_id)
        if n is None or n.status not in ("queued", "held"):
            return n.status if n else None
        ns = await db.get(NotificationSettings, user_id)
        if ns is None or not (ns.whatsapp_number and ns.whatsapp_verified_at):
            n.status, n.error = "skipped", "No verified WhatsApp number"
            return n.status
        if not ns.whatsapp_jobs:
            n.status, n.error = "skipped", "WhatsApp job alerts were turned off"
            return n.status
        row = (
            await db.execute(
                select(UserJob, Job, JobMatch)
                .join(Job, Job.id == UserJob.job_id)
                .join(JobMatch, JobMatch.user_job_id == UserJob.id)
                .where(UserJob.id == n.user_job_id)
            )
        ).first()
        if row is None or row[0].status not in OPEN_STATUSES:
            n.status, n.error = "skipped", "You already acted on this job"
            return n.status
        uj, job, match = row
        n.body = job_line(job.title, job.company, match.score)  # the score when it's sent
        n.attempts += 1
        try:
            sent = await whatsapp.send_job(
                ns.whatsapp_number, job.title, job.company or "", match.score, job_link(uj.id)
            )
        except whatsapp.WhatsAppError as e:
            n.error = str(e)
            if e.permanent or n.attempts >= MAX_ATTEMPTS:
                n.status = "failed"
            else:
                n.status, retry_at = "queued", datetime.now(UTC) + timedelta(minutes=2 * n.attempts)
                n.send_after = retry_at
        else:
            n.status = "sent" if sent.provider_id else "logged"
            n.provider_id, n.sent_at, n.error = sent.provider_id, datetime.now(UTC), None
        status = n.status
    if retry_at:
        await queue_send(user_id, notification_id, retry_at)
    return status


@app.task(name=SEND, queue="notify")
async def send_task(user_id: str, notification_id: str) -> None:
    status = await send(UUID(user_id), UUID(notification_id))
    log.info("notification %s: %s", notification_id, status)
