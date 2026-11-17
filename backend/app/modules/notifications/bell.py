"""The in-app bell (milestone 6.2): what needs the user's attention, in one list, newest first.

Worked out on read from what the app already knows, like a job's to-dos; nothing is copied into a table:
- **strong**: a Strong match first seen in the last 7 days that the user hasn't applied to, ignored or expired;
- **duplicate**: a possible duplicate waiting for Same job / Different job;
- **follow_up**: an application whose follow-up date has come;
- **expiry**: an active job that may have expired (no alert for a while, or its posting is in doubt).

Unread: items newer than the last time the user opened the bell (`notification_settings.bell_seen_at`).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.service import load as load_app_settings
from app.modules.applications import service as applications
from app.modules.applications.models import Application
from app.modules.catalog.models import Job, JobSource
from app.modules.jobs.duplicates import _open as open_pairs
from app.modules.jobs.expiry import ACTIVE, last_sign_of_life, may_have_expired, posting_doubt
from app.modules.jobs.models import UserJob
from app.modules.matching.models import JobMatch

NEW_MATCH_DAYS = 7
LIMIT = 40


@dataclass(frozen=True)
class Item:
    key: str  # stable: "<kind>:<user job id>"
    kind: str  # strong | duplicate | follow_up | expiry
    title: str
    detail: str
    user_job_id: UUID
    at: datetime


def _job(job: Job) -> str:
    return f"{job.title} at {job.company}" if job.company else job.title


async def items(db: AsyncSession, user_id: UUID, now: datetime | None = None) -> list[Item]:
    now = now or datetime.now(UTC)
    tz = await applications.timezone(db, user_id)
    out: list[Item] = []

    strong = await db.execute(
        select(UserJob, Job, JobMatch)
        .join(Job, Job.id == UserJob.job_id)
        .join(JobMatch, JobMatch.user_job_id == UserJob.id)
        .where(
            JobMatch.band == "strong",
            UserJob.status.in_(ACTIVE),
            UserJob.first_seen_at >= now - timedelta(days=NEW_MATCH_DAYS),
        )
    )
    for uj, job, m in strong:
        out.append(
            Item(f"strong:{uj.id}", "strong", f"Top match, {m.score}%", _job(job), uj.id, uj.first_seen_at)
        )

    pairs = (await db.execute(open_pairs())).all()
    if pairs:
        newer = {max(a, b, key=str) for a, b in pairs}  # one item per pair, on either job
        rows = await db.execute(
            select(UserJob, Job).join(Job, Job.id == UserJob.job_id).where(UserJob.id.in_(newer))
        )
        for uj, job in rows:
            out.append(
                Item(
                    f"duplicate:{uj.id}",
                    "duplicate",
                    "Possible duplicate",
                    f"{_job(job)}: the same role as another of your jobs? Decide on its page.",
                    uj.id,
                    uj.first_seen_at,
                )
            )

    today = applications.today(tz)
    due = await db.execute(
        select(Application, Job)
        .join(UserJob, UserJob.id == Application.user_job_id)
        .join(Job, Job.id == UserJob.job_id)
        .where(Application.follow_up_on <= today, Application.status.in_(applications.OPEN))
    )
    for app, job in due:
        at = datetime.combine(app.follow_up_on, time(9, 0), tzinfo=ZoneInfo(tz))
        out.append(
            Item(
                f"follow_up:{app.user_job_id}",
                "follow_up",
                "Follow up on your application",
                f"{_job(job)}: you planned to follow up on {app.follow_up_on:%d %b}.",
                app.user_job_id,
                min(at, now),
            )
        )

    values = await load_app_settings(db)
    active = (
        await db.execute(
            select(UserJob, Job).join(Job, Job.id == UserJob.job_id).where(UserJob.status.in_(ACTIVE))
        )
    ).all()
    sources: dict[UUID, list[str]] = {}
    if active:
        found = await db.execute(
            select(JobSource.job_id, JobSource.source).where(JobSource.job_id.in_({j.id for _, j in active}))
        )
        for job_id, source in found:
            sources.setdefault(job_id, []).append(source)
    for uj, job in active:
        doubt = posting_doubt(job, sources.get(job.id, []), values, now)
        if not may_have_expired(uj, values, now, doubt):
            continue
        if doubt is not None and uj.confirmed_open_at is None:
            title, detail, at = doubt.title, f"{_job(job)}: {doubt.detail}", uj.first_seen_at
        else:
            title = "This job may have expired"
            detail = f"{_job(job)}: no alert has shown it for {values.job_expiry_warn_days} days or more."
            at = last_sign_of_life(uj) + timedelta(days=values.job_expiry_warn_days)
        out.append(Item(f"expiry:{uj.id}", "expiry", title, detail, uj.id, min(at, now)))

    return sorted(out, key=lambda i: i.at, reverse=True)[:LIMIT]
