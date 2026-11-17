"""Applications tracker (you apply yourself; BrewMyJob keeps track), and the contacts you saved on a job."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import User, UserDB
from app.core.errors import AppError, Conflict, NotFound
from app.modules.applications import service
from app.modules.applications.contacts import found_in
from app.modules.applications.models import Application, ApplicationEvent, JobContact
from app.modules.applications.schemas import (
    AppJob,
    ApplicationDetail,
    ApplicationList,
    ApplicationOut,
    ApplicationPatch,
    AppStatus,
    ContactIn,
    ContactList,
    ContactOut,
    ContactPatch,
    EventOut,
    FoundContact,
    NoteIn,
)
from app.modules.catalog.models import Job
from app.modules.documents.models import CoverLetter, Resume
from app.modules.jobs.models import UserJob
from app.modules.matching.models import JobMatch

router = APIRouter(tags=["applications"])
_STALE = "This application was changed elsewhere. Reload and try again."


def _base() -> Select:
    return (
        select(Application, UserJob, Job, JobMatch.score)
        .join(UserJob, UserJob.id == Application.user_job_id)
        .join(Job, Job.id == UserJob.job_id)
        .outerjoin(JobMatch, JobMatch.user_job_id == UserJob.id)
    )


async def _labels(db: AsyncSession) -> tuple[dict[UUID, str], dict[UUID, str]]:
    resumes = {r.id: r.label for r in await db.scalars(select(Resume))}
    letters = {c.id: c.label for c in await db.scalars(select(CoverLetter))}
    return resumes, letters


def _out(app: Application, job: Job, score: int | None, labels, today: date) -> dict:
    resumes, letters = labels
    return {
        "id": app.id,
        "status": app.status,
        "applied_on": app.applied_on,
        "follow_up_on": app.follow_up_on,
        "follow_up_due": service.follow_up_due(app, today),
        "resume_id": app.resume_id,
        "resume_label": resumes.get(app.resume_id) if app.resume_id else None,
        "cover_letter_id": app.cover_letter_id,
        "cover_letter_label": letters.get(app.cover_letter_id) if app.cover_letter_id else None,
        "version": app.version,
        "updated_at": app.updated_at,
        "job": AppJob(
            user_job_id=app.user_job_id,
            title=job.title,
            company=job.company,
            location=job.location,
            score=score,
        ),
    }


def _due(today: date):
    return and_(
        Application.follow_up_on.is_not(None),
        Application.follow_up_on <= today,
        Application.status.in_(service.OPEN),
    )


@router.get("/applications", response_model=ApplicationList)
async def list_applications(
    user: User,
    db: UserDB,
    app_status: Annotated[AppStatus | None, Query(alias="status")] = None,
    day_from: Annotated[date | None, Query(alias="from", description="Applied on or after")] = None,
    day_to: Annotated[date | None, Query(alias="to", description="Applied on or before")] = None,
    due: Annotated[bool, Query(description="Only applications with a follow-up due")] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """Your applications, follow-ups due first, then the most recent. Filter by status and by the date applied
    (a day, a month or a year is a from/to range)."""
    if day_from and day_to and day_from > day_to:
        raise AppError(422, "validation_error", "'from' must be on or before 'to'")
    today = service.today(await service.timezone(db, user.id))
    stmt = _base()
    if app_status:
        stmt = stmt.where(Application.status == app_status)
    if day_from:
        stmt = stmt.where(Application.applied_on >= day_from)
    if day_to:
        stmt = stmt.where(Application.applied_on <= day_to)
    if due:
        stmt = stmt.where(_due(today))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.execute(
            stmt.order_by(
                case((_due(today), 0), else_=1),
                Application.applied_on.desc(),
                Application.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    counts = dict(
        (await db.execute(select(Application.status, func.count()).group_by(Application.status))).all()
    )
    due_count = await db.scalar(select(func.count()).select_from(Application).where(_due(today))) or 0
    labels = await _labels(db)
    return ApplicationList(
        items=[ApplicationOut(**_out(a, job, score, labels, today)) for a, _, job, score in rows],
        total=total,
        limit=limit,
        offset=offset,
        counts=counts,
        follow_ups_due=due_count,
    )


async def _get(db: AsyncSession, application_id: UUID, lock: bool = False):
    stmt = _base().where(Application.id == application_id)
    if lock:
        stmt = stmt.with_for_update(of=Application)
    row = (await db.execute(stmt)).first()
    if row is None:
        raise NotFound("Application")
    return row


async def _detail(db: AsyncSession, user_id: UUID, application_id: UUID) -> ApplicationDetail:
    app, _, job, score = await _get(db, application_id)
    await db.refresh(app)
    today = service.today(await service.timezone(db, user_id))
    events = await db.scalars(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == app.id)
        .order_by(ApplicationEvent.at, ApplicationEvent.id)
    )
    return ApplicationDetail(
        **_out(app, job, score, await _labels(db), today),
        events=[EventOut.model_validate(e) for e in events],
    )


@router.get("/applications/{application_id}", response_model=ApplicationDetail)
async def get_application(application_id: UUID, user: User, db: UserDB):
    return await _detail(db, user.id, application_id)


@router.patch("/applications/{application_id}", response_model=ApplicationDetail)
async def patch_application(application_id: UUID, body: ApplicationPatch, user: User, db: UserDB):
    """Move the application on (Interviewing, Offer…), set or clear a follow-up date, or correct what you sent."""
    app, *_ = await _get(db, application_id, lock=True)
    if body.version != app.version:
        raise Conflict("version_conflict", _STALE)
    sent = body.model_fields_set - {"version"}
    changed = False
    if "status" in sent and body.status and body.status != app.status:
        db.add(
            ApplicationEvent(
                user_id=user.id,
                application_id=app.id,
                kind="status",
                from_status=app.status,
                to_status=body.status,
            )
        )
        app.status, changed = body.status, True
    if "follow_up_on" in sent and body.follow_up_on != app.follow_up_on:
        note = f"{body.follow_up_on:%Y-%m-%d}" if body.follow_up_on else None
        db.add(ApplicationEvent(user_id=user.id, application_id=app.id, kind="follow_up", note=note))
        app.follow_up_on, changed = body.follow_up_on, True
    if "applied_on" in sent and body.applied_on and body.applied_on != app.applied_on:
        app.applied_on, changed = body.applied_on, True
    for field, model in (("resume_id", Resume), ("cover_letter_id", CoverLetter)):
        if field not in sent or getattr(body, field) == getattr(app, field):
            continue
        new = getattr(body, field)
        if new is not None and await db.get(model, new) is None:
            raise AppError(422, "validation_error", f"That {model.__name__.lower()} isn't in your library")
        setattr(app, field, new)
        changed = True
    if changed:
        app.version += 1
    await db.flush()
    return await _detail(db, user.id, app.id)


@router.post(
    "/applications/{application_id}/notes",
    response_model=ApplicationDetail,
    status_code=status.HTTP_201_CREATED,
)
async def add_note(application_id: UUID, body: NoteIn, user: User, db: UserDB):
    """A note on the timeline: who you spoke to, what's next."""
    app, *_ = await _get(db, application_id)
    db.add(ApplicationEvent(user_id=user.id, application_id=app.id, kind="note", note=body.text))
    await db.flush()
    return await _detail(db, user.id, app.id)


# --- Contacts on a job -----------------------------------------------------------------------------


async def _user_job(db: AsyncSession, user_job_id: UUID) -> tuple[UserJob, Job]:
    uj = await db.get(UserJob, user_job_id)
    if uj is None:
        raise NotFound("Job")
    job = await db.get(Job, uj.job_id)
    assert job is not None
    return uj, job


async def _contacts(db: AsyncSession, uj: UserJob, job: Job) -> ContactList:
    rows = list(
        await db.scalars(
            select(JobContact).where(JobContact.user_job_id == uj.id).order_by(JobContact.created_at)
        )
    )
    known = {v.lower() for c in rows for v in (c.email, c.linkedin_url) if v}
    known |= {u.replace("https://linkedin.com/", "https://www.linkedin.com/") for u in known}
    text = "\n".join(t for t in (uj.description, job.description) if t)
    return ContactList(
        from_email=(job.details or {}).get("recruiter"),
        items=[ContactOut.model_validate(c) for c in rows],
        found=[FoundContact(**vars(f)) for f in found_in(text, known)],
    )


@router.get("/jobs/{user_job_id}/contacts", response_model=ContactList)
async def list_contacts(user_job_id: UUID, _: User, db: UserDB):
    uj, job = await _user_job(db, user_job_id)
    return await _contacts(db, uj, job)


@router.post("/jobs/{user_job_id}/contacts", response_model=ContactList, status_code=status.HTTP_201_CREATED)
async def add_contact(user_job_id: UUID, body: ContactIn, user: User, db: UserDB):
    """Save someone you found for this job (from the posting's "Meet the hiring team", say). Saved only:
    BrewMyJob never contacts anyone."""
    uj, job = await _user_job(db, user_job_id)
    count = await db.scalar(
        select(func.count()).select_from(JobContact).where(JobContact.user_job_id == uj.id)
    )
    if (count or 0) >= 10:
        raise AppError(422, "too_many_contacts", "A job can have up to 10 contacts")
    db.add(JobContact(user_id=user.id, user_job_id=uj.id, **body.model_dump()))
    await db.flush()
    return await _contacts(db, uj, job)


async def _contact(db: AsyncSession, user_job_id: UUID, contact_id: UUID, lock: bool = False) -> JobContact:
    c = await db.get(JobContact, contact_id, with_for_update=lock)
    if c is None or c.user_job_id != user_job_id:
        raise NotFound("Contact")
    return c


@router.put("/jobs/{user_job_id}/contacts/{contact_id}", response_model=ContactList)
async def update_contact(user_job_id: UUID, contact_id: UUID, body: ContactPatch, _: User, db: UserDB):
    uj, job = await _user_job(db, user_job_id)
    c = await _contact(db, uj.id, contact_id, lock=True)
    if body.version != c.version:
        raise Conflict("version_conflict", "This contact was changed elsewhere. Reload and try again.")
    for k, v in body.model_dump(exclude={"version"}).items():
        setattr(c, k, v)
    c.version += 1
    await db.flush()
    return await _contacts(db, uj, job)


@router.delete("/jobs/{user_job_id}/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(user_job_id: UUID, contact_id: UUID, _: User, db: UserDB):
    await db.delete(await _contact(db, user_job_id, contact_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
