"""Old jobs: a "May have expired" warning, then Expired by itself. Alerts never say when a job closes, so age is
the signal: days since an alert last showed the job, or since the user said it's still open. The super admin
sets both numbers (app_settings). Applied jobs never expire. An AI assistant's list can also cast doubt on the
posting itself (posting_doubt): that warns, but never expires the job by itself."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, update

from app.core.db import user_scope
from app.modules.admin.service import AppValues
from app.modules.catalog.models import Job
from app.modules.jobs.models import UserJob

ACTIVE = ("new", "seen")


def last_sign_of_life(uj: UserJob) -> datetime:
    return max(uj.last_seen_at, uj.confirmed_open_at or uj.last_seen_at)


@dataclass(frozen=True)
class Doubt:
    title: str
    detail: str


def posting_doubt(
    job: Job, sources: list[str], values: AppValues, now: datetime | None = None
) -> Doubt | None:
    """Why the posting itself may have closed, from what an AI assistant's list said (user, 2026-11-09: "posted
    yesterday" on one site and "23 days ago" on another). Only a warning: it never moves the job to Expired.

    - the listing's application deadline is today or has passed;
    - its posted dates disagree by a week or more (an old job still indexed or re-posted);
    - only the assistant has shown it, and it was posted `job_expiry_warn_days` or more ago.
    """
    now = now or datetime.now(UTC)
    posting = (job.details or {}).get("posting") or {}
    if closes := posting.get("closes_on"):
        day = date.fromisoformat(closes)
        if day < now.date():
            return Doubt(
                "This job may have closed", f"The listing said applications closed on {day:%d %b %Y}."
            )
        if day == now.date():
            return Doubt(
                "Applications close today", f"The listing says applications close today ({day:%d %b %Y})."
            )
    posted = (job.details or {}).get("posted") or ""
    if posting.get("conflict"):
        return Doubt(
            "This job may have expired",
            f"The posting dates disagree (“{posted}”). An old job that is still listed or was re-posted has often "
            "closed.",
        )
    if job.posted_at and set(sources) == {"ai_assistant"}:
        days = (now - job.posted_at).days
        if days >= values.job_expiry_warn_days:
            return Doubt(
                "This job may have expired",
                f"Your AI assistant found it posted about {days} days ago (“{posted}”). Listings this old have "
                "often closed.",
            )
    return None


def may_have_expired(
    uj: UserJob, values: AppValues, now: datetime | None = None, doubt: Doubt | None = None
) -> bool:
    """Active and either quiet for `job_expiry_warn_days`, or its posting is in doubt and the user hasn't said
    it's still open since."""
    if uj.status not in ACTIVE:
        return False
    now = now or datetime.now(UTC)
    if doubt is not None and uj.confirmed_open_at is None:
        return True
    return now - last_sign_of_life(uj) >= timedelta(days=values.job_expiry_warn_days)


async def expire_old_jobs(user_id: UUID, days: int, now: datetime | None = None) -> int:
    """Move this user's active jobs with no sign of life for `days` to Expired. Returns how many."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    alive = func.greatest(
        UserJob.last_seen_at, func.coalesce(UserJob.confirmed_open_at, UserJob.last_seen_at)
    )
    async with user_scope(user_id) as db:
        result = await db.execute(
            update(UserJob)
            .where(UserJob.status.in_(ACTIVE), alive < cutoff)
            .values(
                status="expired",
                expired_at=func.now(),
                expired_by="auto",
                version=UserJob.version + 1,
            )
        )
        return result.rowcount or 0
