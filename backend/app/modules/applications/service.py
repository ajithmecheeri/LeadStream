"""Applications: created when a job is marked Applied, undone only while nothing else has been recorded."""

from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.modules.applications.models import Application, ApplicationEvent
from app.modules.jobs.models import UserJob
from app.modules.matching.models import JobMatch
from app.modules.users.models import User

# Still waiting on someone: a follow-up date on these can fall due.
OPEN = ("applied", "interviewing", "offer")


async def timezone(db: AsyncSession, user_id: UUID) -> str:
    return await db.scalar(select(User.timezone).where(User.id == user_id)) or "UTC"


def today(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()


def follow_up_due(app: Application, on: date) -> bool:
    return app.follow_up_on is not None and app.follow_up_on <= on and app.status in OPEN


async def for_job(db: AsyncSession, user_job_id: UUID) -> Application | None:
    return await db.scalar(select(Application).where(Application.user_job_id == user_job_id))


async def mark_applied(db: AsyncSession, uj: UserJob, on: date | None = None) -> Application:
    """Record the application, with the resume and cover letter BrewMyJob suggested (the user can change them).
    `on`: the day the user applied, when a portal's email says so; else today."""
    existing = await for_job(db, uj.id)
    if existing is not None:
        return existing
    match = await db.get(JobMatch, uj.id)
    app = Application(
        user_id=uj.user_id,
        user_job_id=uj.id,
        applied_on=on or today(await timezone(db, uj.user_id)),
        resume_id=match.best_resume_id if match else None,
        cover_letter_id=match.cover_letter_id if match else None,
    )
    db.add(app)
    await db.flush()
    db.add(ApplicationEvent(user_id=uj.user_id, application_id=app.id, kind="applied", to_status="applied"))
    return app


async def undo_applied(db: AsyncSession, uj: UserJob) -> None:
    """Remove the application made by mistake. Refused once it has a history worth keeping."""
    app = await for_job(db, uj.id)
    if app is None:
        return
    later = await db.scalar(
        select(func.count())
        .select_from(ApplicationEvent)
        .where(ApplicationEvent.application_id == app.id, ApplicationEvent.kind != "applied")
    )
    if later or app.status != "applied" or app.follow_up_on is not None:
        raise Conflict(
            "application_has_history",
            "This application has updates. Change its status (for example to Withdrawn) instead.",
        )
    await db.delete(app)
