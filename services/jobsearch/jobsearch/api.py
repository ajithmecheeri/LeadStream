"""The internal API, version 1 (docs/jobsearch-plan-discovery.md, section 7). Every route needs the service
token; the service is reachable on the internal network only."""

import hmac
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch import resolver, service
from jobsearch.config import get_settings
from jobsearch.connectors import adzuna, board_url
from jobsearch.db import session
from jobsearch.errors import AppError, Conflict, NotFound
from jobsearch.models import (
    SYSTEMS,
    ConnectorRun,
    Employer,
    EmployerBoard,
    Event,
    Listing,
    ListingSource,
    ListingVersion,
    SearchArea,
)
from jobsearch.schemas import (
    DemandIn,
    DemandOut,
    EmployerIn,
    EmployerListingsOut,
    EmployerOut,
    EventOut,
    EventsOut,
    FoundOut,
    ListingDetailOut,
    ListingOut,
    ListingSourceOut,
    LookupIn,
    RunOut,
    SourceOut,
    SuggestedOut,
    VersionOut,
)
from jobsearch.worker import queue_board


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().token
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not expected or not given or not hmac.compare_digest(given, expected):
        raise AppError("unauthorized", "A valid service token is required", status=401)


router = APIRouter(prefix="/v1", dependencies=[Depends(require_token)])
DB = Annotated[AsyncSession, Depends(session)]


def _run(r: ConnectorRun | None) -> RunOut | None:
    return None if r is None else RunOut.model_validate(r, from_attributes=True)


async def _employer_out(db: AsyncSession, employer: Employer, board: EmployerBoard) -> EmployerOut:
    last = await db.scalar(
        select(ConnectorRun)
        .where(ConnectorRun.board_id == board.id)
        .order_by(ConnectorRun.started_at.desc())
        .limit(1)
    )
    return EmployerOut(
        id=employer.id,
        name=employer.name,
        system=board.system,
        board=board.board,
        board_url=board_url(board.system, board.board),
        last_checked_at=board.last_checked_at,
        last_error=board.last_error,
        jobs_total=board.jobs_total,
        jobs_in_scope=board.jobs_in_scope,
        last_run=_run(last),
    )


async def _board_of(db: AsyncSession, employer_id: UUID) -> tuple[Employer, EmployerBoard]:
    employer = await db.get(Employer, employer_id)
    board = await db.scalar(select(EmployerBoard).where(EmployerBoard.employer_id == employer_id).limit(1))
    if employer is None or board is None:
        raise NotFound("Employer")
    return employer, board


@router.post("/employers", response_model=EmployerOut)
async def register(body: EmployerIn, db: DB, response: Response):
    """Register an employer by careers link or by hiring system + board. Safe to repeat: an existing board
    returns its employer (200); a new one is created (201)."""
    if body.url:
        if resolver.is_portal_link(body.url):
            raise AppError(
                "job_portal",
                "BrewMyJob never reads job portals such as LinkedIn or Naukri: their jobs come from your alert emails",
            )
        found = resolver.from_link(body.url)
        if found is None:
            raise AppError("unknown_board", "That link isn't a company careers site or job board we can read")
        system, board = found
    else:
        system, board = body.system, body.board
    if not resolver.valid_board(system, board):
        raise AppError("unknown_board", "That isn't a valid board on that hiring system")
    reg = await service.register(db, body.name or board.split("/")[-1], system, board, body.id)
    response.status_code = status.HTTP_201_CREATED if reg.created else status.HTTP_200_OK
    return await _employer_out(db, reg.employer, reg.board)


@router.post("/employers/lookup", response_model=list[FoundOut])
async def lookup(body: LookupIn):
    """Find an employer's job boards by name or careers link (takes a few seconds)."""
    if resolver.is_portal_link(body.query) and ("/" in body.query or "." in body.query):
        raise AppError(
            "job_portal",
            "BrewMyJob never reads job portals such as LinkedIn or Naukri: their jobs come from your alert emails",
        )
    return [
        FoundOut(**vars(f), board_url=board_url(f.system, f.board)) for f in await resolver.lookup(body.query)
    ]


@router.get("/employers/suggested", response_model=list[SuggestedOut])
async def suggested(location: str | None = None):
    """Employers worth following. A fixed, checked list for now; discovery (step 3) adds to it per location."""
    return [
        SuggestedOut(name=n, system=s, board=b, board_url=board_url(s, b)) for n, s, b in resolver.SUGGESTED
    ]


@router.get("/employers", response_model=list[EmployerOut])
async def employers(db: DB, ids: Annotated[list[UUID] | None, Query(max_length=500)] = None):
    """Employers by id (the ones a user follows), or all of them."""
    q = select(Employer, EmployerBoard).join(EmployerBoard, EmployerBoard.employer_id == Employer.id)
    if ids is not None:
        q = q.where(Employer.id.in_(ids))
    rows = (await db.execute(q.order_by(func.lower(Employer.name)))).all()
    return [await _employer_out(db, e, b) for e, b in rows]


@router.get("/employers/{employer_id}", response_model=EmployerOut)
async def employer(employer_id: UUID, db: DB):
    e, b = await _board_of(db, employer_id)
    return await _employer_out(db, e, b)


MAX_EMPLOYER_LISTINGS = 500


@router.get("/employers/{employer_id}/listings", response_model=EmployerListingsOut)
async def employer_listings(employer_id: UUID, db: DB):
    """The employer's open listings (in the service's country), newest first and without descriptions, with the
    board's last run: which jobs a company has, and which its last check found (user, 2026-11-16)."""
    _, board = await _board_of(db, employer_id)
    rows = list(
        await db.scalars(
            select(Listing)
            .where(Listing.employer_id == employer_id, Listing.status == "active")
            .order_by(Listing.first_seen_at.desc(), Listing.title)
            .limit(MAX_EMPLOYER_LISTINGS)
        )
    )
    sources = await _sources(db, [r.id for r in rows])
    last = await db.scalar(
        select(ConnectorRun)
        .where(ConnectorRun.board_id == board.id)
        .order_by(ConnectorRun.started_at.desc())
        .limit(1)
    )
    return EmployerListingsOut(
        employer_id=employer_id,
        last_run=_run(last),
        listings=[_listing(r, sources[r.id]).model_copy(update={"description": None}) for r in rows],
    )


@router.post("/employers/{employer_id}/check", response_model=RunOut | None)
async def check(employer_id: UUID, db: DB, response: Response, wait: bool = True):
    """Check one employer now. With `wait` (default) the read runs in this request and its run comes back;
    otherwise it is queued (202). At most once every few minutes per employer."""
    _, board = await _board_of(db, employer_id)
    limit = timedelta(minutes=get_settings().check_every_minutes)
    if board.last_checked_at and datetime.now(UTC) - board.last_checked_at < limit:
        raise Conflict(
            "checked_recently",
            "Checked a few minutes ago",
            {"last_checked_at": board.last_checked_at.isoformat()},
        )
    if not wait:
        await queue_board(board.id)
        response.status_code = status.HTTP_202_ACCEPTED
        return None
    await db.commit()  # don't hold this request's transaction open during the read
    return _run(await service.check_board(board.id))


@router.put("/demand/search-areas", response_model=DemandOut)
async def demand(body: DemandIn, db: DB):
    """Replace the search areas (aggregated across users by the app: no user data)."""
    # One area per (location, family), whatever the letter case: {key: (location as first written, titles)}.
    wanted: dict[tuple[str, str], tuple[str, list[str]]] = {}
    for a in body.areas:
        location = " ".join(a.location.split())
        _, titles = wanted.setdefault((location.lower(), a.role_family.strip().lower()), (location, []))
        titles += [t for t in (" ".join(x.split()) for x in a.titles) if t and t not in titles]
    existing = {(r.location.lower(), r.role_family): r for r in await db.scalars(select(SearchArea))}
    now = datetime.now(UTC)
    for (key_location, family), (location, titles) in wanted.items():
        row = existing.pop((key_location, family), None)
        if row is None:
            db.add(SearchArea(location=location, role_family=family, titles=titles[:20], active=True))
        else:
            row.titles, row.active, row.updated_at = titles[:20], True, now
    for row in existing.values():
        if row.active:
            row.active, row.updated_at = False, now
    return DemandOut(active=len(wanted))


async def _sources(db: AsyncSession, ids: list[UUID]) -> dict[UUID, list[ListingSourceOut]]:
    out: dict[UUID, list[ListingSourceOut]] = {i: [] for i in ids}
    if ids:
        for s in await db.scalars(
            select(ListingSource)
            .where(ListingSource.listing_id.in_(ids))
            .order_by(ListingSource.first_seen_at)
        ):
            out[s.listing_id].append(ListingSourceOut.model_validate(s, from_attributes=True))
    return out


def _listing(row: Listing, sources: list[ListingSourceOut]) -> ListingOut:
    return ListingOut(
        listing_id=row.id,
        employer_id=row.employer_id,
        company=row.company,
        title=row.title,
        location=row.location,
        work_model=row.work_model,
        experience=row.experience,
        salary=row.salary,
        description=row.description,
        skills=list(row.skills or []),
        details=dict(row.details or {}),
        posted_at=row.posted_at,
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        closed_at=row.closed_at,
        status=row.status,
        sources=sources,
        requisition_id=row.requisition_id,
        content_hash=row.content_hash,
        version=row.version,
    )


@router.get("/events", response_model=EventsOut)
async def events(db: DB, after: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=1000)):
    """Events after the cursor, oldest first, each with the listing as it is now."""
    rows = (
        await db.execute(
            select(Event, Listing)
            .join(Listing, Listing.id == Event.listing_id)
            .where(Event.id > after)
            .order_by(Event.id)
            .limit(limit)
        )
    ).all()
    sources = await _sources(db, list({listing.id for _, listing in rows}))
    out = [
        EventOut(
            event_id=e.id, type=e.type, occurred_at=e.occurred_at, listing=_listing(row, sources[row.id])
        )
        for e, row in rows
    ]
    return EventsOut(events=out, next_cursor=out[-1].event_id if out else after)


@router.get("/listings/{listing_id}", response_model=ListingDetailOut)
async def listing(listing_id: UUID, db: DB):
    row = await db.get(Listing, listing_id)
    if row is None:
        raise NotFound("Listing")
    versions = await db.scalars(
        select(ListingVersion).where(ListingVersion.listing_id == listing_id).order_by(ListingVersion.version)
    )
    base = _listing(row, (await _sources(db, [row.id]))[row.id])
    return ListingDetailOut(
        **base.model_dump(),
        versions=[
            VersionOut(version=v.version, replaced_at=v.replaced_at, snapshot=v.snapshot) for v in versions
        ],
    )


@router.get("/sources", response_model=list[SourceOut])
async def sources(db: DB):
    """Each connector's health over the last 24 hours."""
    since = datetime.now(UTC) - timedelta(hours=24)
    boards = dict(
        (await db.execute(select(EmployerBoard.system, func.count()).group_by(EmployerBoard.system))).all()
    )
    out = []
    for name in (*SYSTEMS, "adzuna"):
        runs = list(
            await db.scalars(
                select(ConnectorRun)
                .where(ConnectorRun.connector == name, ConnectorRun.started_at >= since)
                .order_by(ConnectorRun.started_at.desc())
            )
        )
        last = (
            runs[0]
            if runs
            else await db.scalar(
                select(ConnectorRun)
                .where(ConnectorRun.connector == name)
                .order_by(ConnectorRun.started_at.desc())
                .limit(1)
            )
        )
        out.append(
            SourceOut(
                connector=name,
                configured=adzuna.configured() if name == "adzuna" else True,
                boards=int(boards.get(name, 0)),
                last_run_at=last.started_at if last else None,
                runs_24h=len(runs),
                failures_24h=sum(1 for r in runs if r.error),
                last_error=next((r.error for r in runs if r.error), None),
            )
        )
    return out


@router.get("/runs", response_model=list[RunOut])
async def runs(
    db: DB,
    kind: str | None = Query(None, pattern="^(connector|discovery)$"),
    since: datetime | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    """Run history, newest first. Discovery runs arrive with step 3."""
    if kind == "discovery":
        return []
    q = select(ConnectorRun).order_by(ConnectorRun.started_at.desc()).limit(limit)
    if since is not None:
        q = q.where(ConnectorRun.started_at >= since)
    return [_run(r) for r in await db.scalars(q)]


@router.post("/boards/check-all", status_code=status.HTTP_202_ACCEPTED)
async def check_all(db: DB):
    """Queue every board now (admin; the 3-hourly schedule does the same)."""
    ids = list(await db.scalars(select(EmployerBoard.id)))
    for board_id in ids:
        await queue_board(board_id)
    return {"queued": len(ids)}
