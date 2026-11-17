"""Networking: your LinkedIn connections (from your own export), warm paths to matching jobs, the day's
suggestions with a note to copy, and the outreach you've done. BrewMyJob never contacts anyone for you."""

import base64
import binascii
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import User, UserDB
from app.core.errors import AppError, Conflict, NotFound
from app.modules.applications.models import Application
from app.modules.applications.service import timezone, today
from app.modules.candidate.models import CandidateProfile
from app.modules.catalog.models import Job
from app.modules.jobs.models import UserJob
from app.modules.networking import notes, service
from app.modules.networking.companies import company_key, search_name
from app.modules.networking.importer import ExportFileError, read_connections
from app.modules.networking.models import Connection, ConnectionImport, Outreach, OutreachEvent, Suggestion
from app.modules.networking.schemas import (
    AppliedCompanies,
    AppliedCompany,
    ConnectionList,
    ConnectionOut,
    Daily,
    ImportIn,
    ImportOut,
    InviteNoteIn,
    InviteNoteOut,
    JobPeople,
    MarkIn,
    NetworkSummary,
    OutreachDetail,
    OutreachEventOut,
    OutreachIn,
    OutreachList,
    OutreachOut,
    OutreachPatch,
    PeopleSearch,
    Stage,
    SuggestionOut,
    WarmPath,
    WarmPaths,
)

router = APIRouter(tags=["networking"])
MAX_BYTES = 10 * 1024 * 1024


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# --- Connections ------------------------------------------------------------------------------------


@router.post("/network/imports", response_model=ImportOut, status_code=status.HTTP_201_CREATED)
async def import_connections(body: ImportIn, user: User, db: UserDB):
    """Upload LinkedIn's Connections export (the CSV, or the ZIP LinkedIn emails). Importing again updates
    people already there and adds new ones; nobody is removed. The file itself isn't kept."""
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise AppError(422, "validation_error", "The file couldn't be read (bad base64)") from e
    if len(data) > MAX_BYTES:
        raise AppError(413, "file_too_large", "The file is larger than 10 MB")
    try:
        people, skipped = read_connections(body.file_name, data, keep_email=body.keep_email)
    except ExportFileError as e:
        raise AppError(422, "not_a_connections_export", str(e)) from e
    if not people:
        raise AppError(422, "not_a_connections_export", "The file has no connections in it")

    imp = ConnectionImport(user_id=user.id, file_name=body.file_name, kept_email=body.keep_email)
    db.add(imp)
    await db.flush()
    existing = {c.person_key: c for c in await db.scalars(select(Connection))}
    added = updated = 0
    for p in people:
        row = existing.get(p.person_key)
        fields = {k: v for k, v in p.__dict__.items() if k != "person_key"}
        if not body.keep_email:
            fields.pop("email")  # keep an email saved by an earlier import that kept them
        if row is None:
            db.add(Connection(user_id=user.id, person_key=p.person_key, import_id=imp.id, **fields))
            added += 1
        else:
            if any(getattr(row, k) != v for k, v in fields.items()):
                updated += 1
            for k, v in fields.items():
                setattr(row, k, v)
            row.import_id = imp.id
    imp.total, imp.added, imp.updated, imp.skipped = len(people), added, updated, skipped
    await db.flush()
    await db.refresh(imp)
    return imp


@router.get("/network/summary", response_model=NetworkSummary)
async def summary(_: User, db: UserDB):
    total, companies = (
        await db.execute(select(func.count(), func.count(func.distinct(Connection.company_key))))
    ).one()
    last = await db.scalar(select(ConnectionImport).order_by(ConnectionImport.created_at.desc()).limit(1))
    index = await service.people_by_company(db)
    warm = sum(1 for t in await service.targets(db) if service.people_at(t.job.company, index))
    return NetworkSummary(
        connections=total,
        companies=companies,
        last_import=ImportOut.model_validate(last) if last else None,
        warm_jobs=warm,
    )


@router.get("/network/connections", response_model=ConnectionList)
async def list_connections(
    _: User,
    db: UserDB,
    q: Annotated[str | None, Query(max_length=100, description="Name, company or position")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    stmt = select(Connection)
    if q and q.strip():
        pattern = _like(" ".join(q.split()))
        stmt = stmt.where(
            or_(
                func.concat_ws(" ", Connection.first_name, Connection.last_name).ilike(pattern),
                Connection.company.ilike(pattern),
                Connection.position.ilike(pattern),
            )
        )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = await db.scalars(
        stmt.order_by(Connection.company_key.nulls_last(), Connection.first_name, Connection.id)
        .limit(limit)
        .offset(offset)
    )
    return ConnectionList(
        items=[ConnectionOut.model_validate(c) for c in rows], total=total, limit=limit, offset=offset
    )


@router.delete("/network/connections", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connections(_: User, db: UserDB):
    """Remove every imported connection (and the import history). Your outreach records stay."""
    await db.execute(delete(Connection))
    await db.execute(delete(ConnectionImport))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Warm paths -------------------------------------------------------------------------------------


@router.get("/network/warm-paths", response_model=WarmPaths)
async def warm_paths(_: User, db: UserDB):
    """Top matches and applied jobs at companies where you know someone, best match first."""
    index = await service.people_by_company(db)
    items = []
    for t in await service.targets(db):
        people = service.people_at(t.job.company, index)
        if people:
            items.append(
                WarmPath(
                    user_job_id=t.uj.id,
                    title=t.job.title,
                    company=t.job.company or "",
                    score=t.score,
                    status=t.uj.status,
                    people=[ConnectionOut.model_validate(c) for c in people[:5]],
                    total_people=len(people),
                )
            )
    return WarmPaths(items=items)


@router.get("/jobs/{user_job_id}/people", response_model=JobPeople)
async def job_people(user_job_id: UUID, _: User, db: UserDB):
    """People you know at this job's company."""
    uj = await db.get(UserJob, user_job_id)
    if uj is None:
        raise NotFound("Job")
    job = await db.get(Job, uj.job_id)
    assert job is not None
    imported = (await db.scalar(select(func.count()).select_from(Connection))) or 0
    people = service.people_at(job.company, await service.people_by_company(db)) if imported else []
    return JobPeople(
        company=job.company,
        items=[ConnectionOut.model_validate(c) for c in people[:20]],
        imported=bool(imported),
    )


# --- Companies you applied to ----------------------------------------------------------------------

APPLIED_DAYS = 60
APPLIED_MAX = 10
APPLIED_CLOSED = ("rejected", "withdrawn")


@router.get("/network/applied", response_model=AppliedCompanies)
async def applied_companies(user: User, db: UserDB):
    """Companies you applied to in the last 60 days, newest first: LinkedIn people searches for their HR and
    leaders (you open them yourself), a note to copy, and anyone you already know there."""
    since = today(await timezone(db, user.id)) - timedelta(days=APPLIED_DAYS)
    rows = (
        await db.execute(
            select(Application, UserJob, Job)
            .join(UserJob, UserJob.id == Application.user_job_id)
            .join(Job, Job.id == UserJob.job_id)
            .where(
                Application.applied_on >= since,
                Application.status.not_in(APPLIED_CLOSED),
                Job.company.is_not(None),
            )
            .order_by(Application.applied_on.desc(), Application.created_at.desc())
        )
    ).all()
    picked, seen = [], set()
    for app_, uj, job in rows:
        key, name = company_key(job.company), search_name(job.company)
        if not key or not name or key in seen:
            continue
        seen.add(key)
        picked.append((app_, uj, job, name))
        if len(picked) >= APPLIED_MAX:
            break
    if not picked:
        return AppliedCompanies(days=APPLIED_DAYS, items=[])
    contacted = dict(
        (
            await db.execute(
                select(Outreach.user_job_id, func.count())
                .where(Outreach.user_job_id.in_([uj.id for _, uj, _, _ in picked]))
                .group_by(Outreach.user_job_id)
            )
        ).all()
    )
    index = await service.people_by_company(db)
    me, headline, _ = await service.about_me(db, user.id)
    items = []
    for app_, uj, job, name in picked:
        people = service.people_at(job.company, index)
        items.append(
            AppliedCompany(
                user_job_id=uj.id,
                company=name,
                job_title=job.title,
                applied_on=app_.applied_on,
                status=app_.status,
                searches=[
                    PeopleSearch(kind=k, label=label, url=url)
                    for k, label, url in notes.people_searches(name, job.title)
                ],
                note=notes.applied(name, job.title, headline, me),
                people=[ConnectionOut.model_validate(c) for c in people[:3]],
                total_people=len(people),
                contacted=contacted.get(uj.id, 0),
            )
        )
    return AppliedCompanies(days=APPLIED_DAYS, items=items)


# --- Today ------------------------------------------------------------------------------------------


def _suggestion(s: Suggestion) -> SuggestionOut:
    p = s.payload or {}
    return SuggestionOut(
        id=s.id,
        kind=s.kind,
        status=s.status,
        name=p.get("name"),
        title=p.get("title"),
        role=p.get("role"),
        company=p.get("company"),
        profile_url=p.get("profile_url"),
        search_url=p.get("search_url"),
        user_job_id=s.user_job_id,
        job_title=p.get("job_title"),
        job_score=p.get("job_score"),
        why=p.get("why", ""),
        note=p.get("note", ""),
        outreach_id=s.outreach_id,
    )


@router.get("/network/daily", response_model=Daily)
async def daily(
    user: User,
    db: UserDB,
    day: Annotated[date | None, Query(alias="date", description="Your date; today when left out")] = None,
    regenerate: Annotated[bool, Query(description="Replace today's open suggestions")] = False,
):
    """Today's people to contact: warm paths, people to find at matching companies, and follow-ups. Each has
    a short note to copy. You send everything yourself on LinkedIn, then mark it sent."""
    now_day = today(await timezone(db, user.id))
    day = day or now_day
    if day > now_day:
        raise AppError(422, "validation_error", "That day hasn't come yet")
    if day < now_day and regenerate:
        raise AppError(422, "validation_error", "Only today's list can be rebuilt")
    items = (
        await service.build_day(db, user.id, day, regenerate)
        if day == now_day
        else list(
            await db.scalars(select(Suggestion).where(Suggestion.day == day).order_by(Suggestion.position))
        )
    )
    cap, weekly_limit = await service.limits(db, user.id)
    return Daily(
        date=day,
        cap=cap,
        weekly_sent=await service.weekly_sent(db, datetime.now(UTC)),
        weekly_limit=weekly_limit,
        items=[_suggestion(s) for s in items],
    )


async def _invite_note(db: AsyncSession, user_id: UUID) -> InviteNoteOut:
    me, headline, own = await service.about_me(db, user_id)
    return InviteNoteOut(note=own, example=notes.target("Acme", "Director of Engineering", headline, me, own))


@router.get("/network/invite-note", response_model=InviteNoteOut)
async def get_invite_note(user: User, db: UserDB):
    """Your note for invitations to people you don't know yet (the "find someone" suggestions)."""
    return await _invite_note(db, user.id)


@router.put("/network/invite-note", response_model=InviteNoteOut)
async def put_invite_note(body: InviteNoteIn, user: User, db: UserDB):
    """Write your own invitation note (at most 300 characters, LinkedIn's limit; your first name is added when it
    fits). Empty goes back to ours. Today's open suggestions take the new note."""
    if await db.get(CandidateProfile, user.id) is None:
        raise NotFound("Candidate profile")
    await service.set_invite_note(db, user.id, body.note)
    await db.flush()
    return await _invite_note(db, user.id)


@router.post("/network/suggestions/{suggestion_id}/mark", response_model=SuggestionOut)
async def mark(suggestion_id: UUID, body: MarkIn, user: User, db: UserDB):
    """You sent it (an outreach is recorded, or a follow-up noted on the existing one), or you skipped it."""
    s = await db.get(Suggestion, suggestion_id, with_for_update=True)
    if s is None:
        raise NotFound("Suggestion")
    if s.status != "open":
        raise Conflict("already_marked", "This suggestion was already marked")
    if body.action == "skipped":
        s.status = "skipped"
        await db.flush()
        return _suggestion(s)

    p = s.payload or {}
    note = (body.note or "").strip() or p.get("note")
    if s.kind == "followup":
        o = await db.get(Outreach, s.outreach_id) if s.outreach_id else None
        if o is None:
            raise NotFound("Outreach")
        o.followed_up_at = datetime.now(UTC)
        o.version += 1
        db.add(OutreachEvent(user_id=user.id, outreach_id=o.id, kind="followed_up", note=note))
    else:
        person = body.person
        o = Outreach(
            user_id=user.id,
            kind=s.kind,
            person_name=(person.name if person and person.name else p.get("name")),
            title=(person.title if person and person.title else p.get("title") or p.get("role")),
            company=p.get("company"),
            profile_url=(person.profile_url if person and person.profile_url else p.get("profile_url")),
            connection_id=s.connection_id,
            user_job_id=s.user_job_id,
            note=note,
        )
        db.add(o)
        await db.flush()
        db.add(OutreachEvent(user_id=user.id, outreach_id=o.id, kind="sent", stage="sent", note=note))
        s.outreach_id = o.id
    s.status = "done"
    await db.flush()
    return _suggestion(s)


# --- Outreach ---------------------------------------------------------------------------------------


async def _job_titles(db: AsyncSession, ids: list[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    rows = await db.execute(
        select(UserJob.id, Job.title).join(Job, Job.id == UserJob.job_id).where(UserJob.id.in_(ids))
    )
    return dict(rows.all())


def _outreach(o: Outreach, titles: dict[UUID, str]) -> dict:
    return {
        **OutreachOut.model_validate(o).model_dump(exclude={"job_title"}),
        "job_title": titles.get(o.user_job_id) if o.user_job_id else None,
    }


async def _detail(db: AsyncSession, o: Outreach) -> OutreachDetail:
    await db.refresh(o)
    events = await db.scalars(
        select(OutreachEvent)
        .where(OutreachEvent.outreach_id == o.id)
        .order_by(OutreachEvent.at, OutreachEvent.id)
    )
    titles = await _job_titles(db, [o.user_job_id] if o.user_job_id else [])
    return OutreachDetail(**_outreach(o, titles), events=[OutreachEventOut.model_validate(e) for e in events])


@router.get("/network/outreach", response_model=OutreachList)
async def list_outreach(_: User, db: UserDB, stage: Stage | None = None):
    """Everyone you've contacted, most recent first."""
    stmt = select(Outreach).order_by(Outreach.stage_at.desc(), Outreach.created_at.desc())
    if stage:
        stmt = stmt.where(Outreach.stage == stage)
    rows = list(await db.scalars(stmt.limit(200)))
    counts = dict((await db.execute(select(Outreach.stage, func.count()).group_by(Outreach.stage))).all())
    titles = await _job_titles(db, [o.user_job_id for o in rows if o.user_job_id])
    return OutreachList(items=[OutreachOut(**_outreach(o, titles)) for o in rows], counts=counts)


@router.post("/network/outreach", response_model=OutreachDetail, status_code=status.HTTP_201_CREATED)
async def add_outreach(body: OutreachIn, user: User, db: UserDB):
    """Record someone you contacted yourself, outside today's suggestions."""
    if body.user_job_id and await db.get(UserJob, body.user_job_id) is None:
        raise AppError(422, "validation_error", "That job isn't in your list")
    o = Outreach(user_id=user.id, kind="manual", **body.model_dump())
    db.add(o)
    await db.flush()
    db.add(OutreachEvent(user_id=user.id, outreach_id=o.id, kind="sent", stage="sent", note=body.note))
    await db.flush()
    return await _detail(db, o)


@router.get("/network/outreach/{outreach_id}", response_model=OutreachDetail)
async def get_outreach(outreach_id: UUID, _: User, db: UserDB):
    o = await db.get(Outreach, outreach_id)
    if o is None:
        raise NotFound("Outreach")
    return await _detail(db, o)


@router.patch("/network/outreach/{outreach_id}", response_model=OutreachDetail)
async def patch_outreach(outreach_id: UUID, body: OutreachPatch, user: User, db: UserDB):
    """Move it on: they accepted, you're talking, they referred you, or it's closed."""
    o = await db.get(Outreach, outreach_id, with_for_update=True)
    if o is None:
        raise NotFound("Outreach")
    if body.version != o.version:
        raise Conflict("version_conflict", "This outreach was changed elsewhere. Reload and try again.")
    changed = False
    if body.stage and body.stage != o.stage:
        o.stage, o.stage_at, changed = body.stage, datetime.now(UTC), True
        db.add(OutreachEvent(user_id=user.id, outreach_id=o.id, kind="stage", stage=body.stage))
    if "note" in body.model_fields_set and (body.note or None) != o.note:
        o.note, changed = (body.note or "").strip() or None, True
    if changed:
        o.version += 1
    await db.flush()
    return await _detail(db, o)
