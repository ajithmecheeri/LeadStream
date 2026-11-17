"""Job sources besides alert emails: the companies BrewMyJob reads and Adzuna, served by the Job Search Service
(docs/plan-jobsearch-build.md). Since 2026-11-17 the admins keep one shared list of companies (Job sources is for
admins); every user gets the jobs that fit them, and sees all the others in Jobs -> From sources
(docs/plan-roles-and-plans.md)."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import delete, func, select, text

from app.core.deps import CurrentUser, User, UserDB, require_admin
from app.core.errors import AppError, Conflict, NotFound
from app.modules.applications.service import timezone as user_timezone
from app.modules.catalog.models import Job, JobSource
from app.modules.jobs.models import UserJob
from app.modules.matching.models import JobMatch
from app.modules.matching.service import queue_scoring
from app.modules.sources import client
from app.modules.sources.models import JobSearchSync, PlatformCompany, SourceRun
from app.modules.sources.relevance import audience, why_not
from app.modules.sources.schemas import (
    AdzunaOut,
    CompanyIn,
    CompanyJobOut,
    CompanyJobsOut,
    CompanyOut,
    ConnectorOut,
    FoundBoardOut,
    LastCheckOut,
    LastRunOut,
    LookupIn,
    RunJobOut,
    RunJobsOut,
    SourceJobsOut,
    SourceRunOut,
    SourcesOut,
    SuggestedCompanyOut,
    SuggestedIn,
)
from app.modules.sources.sync import card_of, catalog_ids
from app.modules.sources.tasks import REFRESH_USER, check_times, next_check, queue_refresh

router = APIRouter(prefix="/sources", tags=["sources"])
Admin = Annotated[CurrentUser, Depends(require_admin)]
CHECK_EVERY = timedelta(minutes=10)
MAX_ADZUNA_SEARCHES = 10  # shown on the page (the service searches the shared areas)


def _unavailable(e: Exception) -> AppError:
    return AppError(
        503, "jobsearch_unavailable", "Job search can't be reached right now. Try again in a minute."
    )


def _refused(e: client.Refused) -> AppError:
    return AppError(400 if e.status < 500 else 503, e.code, e.message)


def _run(r: SourceRun | None, added: int | None = None) -> SourceRunOut | None:
    if r is None:
        return None
    return SourceRunOut(
        ran_at=r.ran_at,
        found=r.found,
        added=r.added if added is None else added,
        skipped=r.skipped,
        error=r.error,
    )


ONE_CHECK = timedelta(minutes=5)  # a check's lines for one source: the pull's, then the open jobs caught up


async def _latest_runs(db, source: str) -> dict[UUID | None, SourceRunOut]:
    """Each source's latest line, with `added` counting every line of that check (a check writes the pull's line,
    then the line of the open jobs it caught up)."""
    lines = await _latest_lines(db, source)
    if not lines:
        return {}
    since = min(r.ran_at for r in lines.values()) - ONE_CHECK
    added: dict[UUID | None, int] = {}
    for eid, ran_at, n in (
        await db.execute(
            select(SourceRun.employer_id, SourceRun.ran_at, SourceRun.added).where(
                SourceRun.source == source, SourceRun.ran_at >= since
            )
        )
    ).all():
        last = lines.get(eid)
        if last is not None and last.ran_at - ONE_CHECK <= ran_at <= last.ran_at:
            added[eid] = added.get(eid, 0) + n
    out = {eid: _run(r, added.get(eid, r.added)) for eid, r in lines.items()}
    return {eid: r for eid, r in out.items() if r is not None}


async def _latest_lines(db, source: str) -> dict[UUID | None, SourceRun]:
    latest = (
        select(SourceRun.employer_id, func.max(SourceRun.ran_at).label("ran_at"))
        .where(SourceRun.source == source)
        .group_by(SourceRun.employer_id)
        .subquery()
    )
    rows = await db.scalars(
        select(SourceRun)
        .join(
            latest,
            SourceRun.employer_id.is_not_distinct_from(latest.c.employer_id)
            & (SourceRun.ran_at == latest.c.ran_at),
        )
        .where(SourceRun.source == source)
    )
    return {r.employer_id: r for r in rows}


@router.get("", response_model=SourcesOut)
async def sources(user: Admin, db: UserDB):
    watched = list(await db.scalars(select(PlatformCompany).order_by(func.lower(PlatformCompany.name))))
    ids = [w.employer_id for w in watched]
    available = True
    employers: dict[str, dict] = {}
    suggested: list[dict] = []
    connectors: list[dict] = []
    try:
        async with client.connect() as js:
            employers = {e["id"]: e for e in await js.employers(ids)}
            suggested = await js.suggested()
            connectors = await js.sources()
    except (client.Unavailable, client.Refused):
        available = False

    runs = await _latest_runs(db, "company_feed")
    adzuna_run = (await _latest_runs(db, "adzuna")).get(None)
    added = dict(
        (
            await db.execute(
                select(SourceRun.employer_id, func.sum(SourceRun.added)).group_by(SourceRun.employer_id)
            )
        ).all()
    )
    who = await audience(db, user.id)
    checking = await db.scalar(
        text(
            "select exists (select 1 from procrastinate_jobs where task_name = :t "
            "and args->>'user_id' = :u and status in ('todo', 'doing'))"
        ),
        {"t": REFRESH_USER, "u": str(user.id)},
    )
    companies = []
    for w in watched:
        e = employers.get(str(w.employer_id)) or {}
        companies.append(
            CompanyOut(
                id=w.employer_id,
                name=e.get("name") or w.name or "Company",
                ats=e.get("system"),
                board=e.get("board"),
                board_url=e.get("board_url"),
                jobs_india=e.get("jobs_in_scope"),
                last_checked_at=e.get("last_checked_at"),
                last_error=e.get("last_error"),
                my_jobs=int(added.get(w.employer_id) or 0),
                last_run=runs.get(w.employer_id),
            )
        )
    watching = {(e["system"], e["board"].lower()) for e in employers.values()}
    adzuna = next((c for c in connectors if c["connector"] == "adzuna"), None)
    now = datetime.now(UTC)
    return SourcesOut(
        companies=sorted(companies, key=lambda c: c.name.lower()),
        suggestions=[
            SuggestedCompanyOut(
                name=s["name"],
                ats=s["system"],
                board=s["board"],
                watching=(s["system"], s["board"].lower()) in watching,
            )
            for s in suggested
        ],
        adzuna=AdzunaOut(
            configured=bool(adzuna and adzuna["configured"]),
            searches=[f"{role} in {loc}" if loc else role for role, loc in who.queries[:MAX_ADZUNA_SEARCHES]],
            last_run=adzuna_run,
        ),
        checking=bool(checking),
        last_run=await _last_run(db),
        last_check=_last_check([runs[i] for i in ids if i in runs] + ([adzuna_run] if adzuna_run else [])),
        next_check_at=next_check(now),
        check_times=check_times(await user_timezone(db, user.id), now),
        service_available=available,
        connectors=[ConnectorOut(**c) for c in connectors],
    )


TOP_BANDS = ("strong", "good")  # Top matches (jobs/router.py)


def _window(sync: JobSearchSync) -> tuple[datetime, datetime]:
    """The pull's own lines: written while it ran, before `last_pull_at`. A company check writes its lines just
    after the pull it triggers; they list the whole board, not what the run brought (2026-11-16: "120 fit your
    profile" for a run that pulled 2 jobs)."""
    assert sync.last_pull_started_at is not None and sync.last_pull_at is not None
    return sync.last_pull_started_at, sync.last_pull_at


async def _last_run(db) -> LastRunOut | None:
    """The service's last run that brought jobs: what it pulled for everyone, and what of it reached you (your
    run lines and the jobs added to your list while it ran)."""
    sync = await db.get(JobSearchSync, 1)
    if sync is None or sync.last_pull_at is None or sync.last_pull_started_at is None:
        return None
    start, end = _window(sync)
    fit, added = (
        await db.execute(
            select(
                func.coalesce(func.sum(SourceRun.found - SourceRun.skipped), 0),
                func.coalesce(func.sum(SourceRun.added), 0),
            ).where(
                SourceRun.source.in_(("company_feed", "adzuna")),
                SourceRun.ran_at >= start,
                SourceRun.ran_at <= end,
            )
        )
    ).one()
    top = await db.scalar(
        select(func.count())
        .select_from(UserJob)
        .join(JobMatch, JobMatch.user_job_id == UserJob.id)
        .where(
            UserJob.first_seen_at >= start,
            UserJob.first_seen_at <= end,
            UserJob.status != "duplicate",
            UserJob.lead.in_(("company_feed", "job_board")),
            JobMatch.band.in_(TOP_BANDS),
        )
    )
    return LastRunOut(
        ran_at=sync.last_pull_at,
        jobs=sync.last_pull_jobs or 0,
        new=sync.last_pull_new or 0,
        updated=sync.last_pull_updated or 0,
        closed=sync.last_pull_closed or 0,
        fit=int(fit),
        added=int(added),
        top_matches=int(top or 0),
    )


LAST_CHECK_WINDOW = timedelta(minutes=30)  # runs this close to the latest one belong to the same check


def _last_check(runs: list[SourceRunOut]) -> LastCheckOut | None:
    """The latest check, summed over the sources it covered (each source's latest run within the window)."""
    if not runs:
        return None
    latest = max(r.ran_at for r in runs)
    same = [r for r in runs if r.ran_at >= latest - LAST_CHECK_WINDOW]
    return LastCheckOut(
        ran_at=latest,
        sources=len(same),
        found=sum(r.found for r in same),
        added=sum(r.added for r in same),
        skipped=sum(r.skipped for r in same),
        errors=sum(1 for r in same if r.error),
    )


@router.post("/lookup", response_model=list[FoundBoardOut])
async def lookup(body: LookupIn, user: Admin):
    """Find a company's public job board by name or careers-page link (takes a few seconds)."""
    try:
        async with client.connect() as js:
            found = await js.lookup(body.query)
    except client.Unavailable as e:
        raise _unavailable(e) from e
    except client.Refused as e:
        raise _refused(e) from e
    return [
        FoundBoardOut(
            ats=f["system"],
            board=f["board"],
            board_url=f["board_url"],
            india=f["in_scope"],
            total=f["total"],
            sample=f["sample"],
        )
        for f in found
    ]


async def _follow(db, user_id: UUID, js: client.JobSearch, name: str, **board) -> UUID:
    try:
        employer = await js.register(name=name, **board)
    except client.Refused as e:
        raise _refused(e) from e
    eid = UUID(employer["id"])
    if await db.get(PlatformCompany, eid) is None:
        db.add(PlatformCompany(employer_id=eid, name=employer["name"], added_by=user_id))
    return eid


@router.post("/companies", status_code=status.HTTP_202_ACCEPTED)
async def add_company(body: CompanyIn, user: Admin, db: UserDB):
    """Add a company's job board to the shared list (found by the lookup, or by its careers link, e.g. a Workday
    site). Its jobs are checked straight away, in the background, and the open ones that fit reach every user."""
    board = {"url": body.url} if body.url else {"system": body.ats, "board": body.board}
    try:
        async with client.connect() as js:
            eid = await _follow(db, user.id, js, body.name, **board)
    except client.Unavailable as e:
        raise _unavailable(e) from e
    await queue_refresh(user.id, [eid])
    return {"id": eid}


@router.post("/companies/suggested", status_code=status.HTTP_202_ACCEPTED)
async def add_suggested(body: SuggestedIn, user: Admin, db: UserDB):
    try:
        async with client.connect() as js:
            known = {f"{s['system']}:{s['board']}": s for s in await js.suggested()}
            picked = [known[k] for k in dict.fromkeys(body.boards) if k in known]
            if not picked:
                raise NotFound("Suggested company")
            ids = [
                await _follow(db, user.id, js, s["name"], system=s["system"], board=s["board"])
                for s in picked
            ]
    except client.Unavailable as e:
        raise _unavailable(e) from e
    await queue_refresh(user.id, ids)
    return {"ids": ids}


@router.delete("/companies/{employer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_company(employer_id: UUID, user: Admin, db: UserDB):
    """Take a company off the shared list. Jobs already in users' lists stay."""
    result = await db.execute(delete(PlatformCompany).where(PlatformCompany.employer_id == employer_id))
    if not result.rowcount:
        raise NotFound("Company")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/check", status_code=status.HTTP_202_ACCEPTED)
async def check_now(user: Admin, db: UserDB):
    """Check every followed company now (at most once every 10 minutes). Adzuna runs on the shared schedule."""
    last = await db.scalar(select(func.max(SourceRun.ran_at)))
    if last and datetime.now(UTC) - last < CHECK_EVERY:
        minutes = int((datetime.now(UTC) - last).total_seconds() // 60)
        raise Conflict("checked_recently", f"Checked {minutes} min ago. Try again in a few minutes.")
    await queue_refresh(user.id)
    return {"queued": True}


# --- The last run's jobs, kept or not (user, 2026-11-16) ---------------------------------------------------------


async def _run_jobs(db) -> tuple[datetime, dict[UUID, tuple[str | None, UUID | None]]] | None:
    """The last run's jobs for this user: job id → (why left out, employer)."""
    sync = await db.get(JobSearchSync, 1)
    if sync is None or sync.last_pull_at is None or sync.last_pull_started_at is None:
        return None
    start, end = _window(sync)
    runs = await db.scalars(
        select(SourceRun).where(
            SourceRun.source.in_(("company_feed", "adzuna")),
            SourceRun.ran_at >= start,
            SourceRun.ran_at <= end,
        )
    )
    jobs: dict[UUID, tuple[str | None, UUID | None]] = {}
    for run in runs:
        for j in run.jobs or []:
            jobs.setdefault(UUID(j["job_id"]), (j.get("why"), run.employer_id))
    return sync.last_pull_at, jobs


@router.get("/last-run/jobs", response_model=RunJobsOut)
async def last_run_jobs(_: User, db: UserDB):
    """Every job the job search service's last run brought for you: the ones in your list (with their score) and
    the ones left out, with the reason (another field, below your level, not one of your locations)."""
    found = await _run_jobs(db)
    if found is None:
        raise NotFound("Last run")
    ran_at, jobs = found
    rows = await db.execute(select(Job).where(Job.id.in_(list(jobs)))) if jobs else None
    catalog = {j.id: j for j in rows.scalars()} if rows is not None else {}
    mine = (
        {
            uj.job_id: (uj, m)
            for uj, m in (
                await db.execute(
                    select(UserJob, JobMatch)
                    .outerjoin(JobMatch, JobMatch.user_job_id == UserJob.id)
                    .where(UserJob.job_id.in_(list(jobs)))
                )
            ).all()
        }
        if jobs
        else {}
    )
    urls: dict[UUID, str] = {}
    if jobs:
        for job_id, url in (
            await db.execute(
                select(JobSource.job_id, JobSource.url).where(
                    JobSource.job_id.in_(list(jobs)), JobSource.url.is_not(None)
                )
            )
        ).all():
            urls.setdefault(job_id, url)
    items = []
    for job_id, (why, _employer) in jobs.items():
        job = catalog.get(job_id)
        if job is None:
            continue
        uj, m = mine.get(job_id, (None, None))
        items.append(
            RunJobOut(
                job_id=job_id,
                title=job.title,
                company=job.company,
                location=job.location,
                url=urls.get(job_id),
                in_list=uj is not None,
                user_job_id=uj.id if uj else None,
                status=uj.status if uj else None,
                score=m.score if m else None,
                band=m.band if m else None,
                why=None if uj is not None else why,
            )
        )
    items.sort(key=lambda i: (not i.in_list, -(i.score or 0), i.title.lower()))
    kept = sum(1 for i in items if i.in_list)
    return RunJobsOut(ran_at=ran_at, items=items, in_list=kept, left_out=len(items) - kept)


@router.post("/last-run/jobs/{job_id}", response_model=RunJobOut, status_code=status.HTTP_201_CREATED)
async def add_run_job(job_id: UUID, user: User, db: UserDB):
    """Add a job the last run left out to your list anyway. It is scored like any other job."""
    found = await _run_jobs(db)
    if found is None or job_id not in found[1]:
        raise NotFound("Job in the last run")
    _why, employer = found[1][job_id]
    return await _add_job(db, user.id, job_id, "company_feed" if employer else "job_board", "the last run")


async def _add_job(db, user_id: UUID, job_id: UUID, lead: str, where: str) -> RunJobOut:
    """Put a catalog job in the user's list anyway (it was left out), and score it."""
    if await db.scalar(select(UserJob.id).where(UserJob.job_id == job_id)):
        raise Conflict("already_in_list", "This job is already in your list")
    job = await db.get(Job, job_id)
    if job is None:
        raise NotFound("Job")
    uj = UserJob(user_id=user_id, job_id=job_id, lead=lead)
    db.add(uj)
    await db.flush()
    await queue_scoring(user_id, f"added from {where}", user_job_ids=[uj.id], delay=0)
    url = await db.scalar(select(JobSource.url).where(JobSource.job_id == job_id, JobSource.url.is_not(None)))
    return RunJobOut(
        job_id=job_id,
        title=job.title,
        company=job.company,
        location=job.location,
        url=url,
        in_list=True,
        user_job_id=uj.id,
        status=uj.status,
        score=None,
        band=None,
        why=None,
    )


# --- A followed company's open jobs, kept or not (user, 2026-11-16) ------------------------------------------


async def _company(db, employer_id: UUID) -> tuple[PlatformCompany, dict, dict[str, UUID]]:
    """The company on the shared list, its open listings from the job search service, and each listing's catalog
    job."""
    followed = await db.get(PlatformCompany, employer_id)
    if followed is None:
        raise NotFound("Company")
    try:
        async with client.connect() as js:
            data = await js.listings(employer_id)
    except client.Unavailable as e:
        raise _unavailable(e) from e
    except client.Refused as e:
        raise _refused(e) from e
    return followed, data, await catalog_ids(db, data.get("listings") or [])


@router.get("/companies/{employer_id}/jobs", response_model=CompanyJobsOut)
async def company_jobs(employer_id: UUID, user: Admin, db: UserDB):
    """Every open India job at a company you follow: the ones in your list (with their score), the ones left out
    and why, and which of them its last check found."""
    followed, data, catalog = await _company(db, employer_id)
    last = data.get("last_run") or {}
    started = datetime.fromisoformat(last["started_at"]) if last.get("started_at") else None
    checked = datetime.fromisoformat(last["finished_at"]) if last.get("finished_at") else started
    ids = list(set(catalog.values()))
    mine = (
        {
            uj.job_id: (uj, m)
            for uj, m in (
                await db.execute(
                    select(UserJob, JobMatch)
                    .outerjoin(JobMatch, JobMatch.user_job_id == UserJob.id)
                    .where(UserJob.job_id.in_(ids))
                )
            ).all()
        }
        if ids
        else {}
    )
    who = await audience(db, user.id)
    items = []
    for listing in data.get("listings") or []:
        card = card_of(listing)
        if card is None:
            continue
        job_id = catalog.get(listing["listing_id"])
        uj, m = mine.get(job_id, (None, None)) if job_id else (None, None)
        seen = datetime.fromisoformat(listing["first_seen_at"])
        items.append(
            CompanyJobOut(
                job_id=job_id,
                title=card.title,
                company=card.company,
                location=card.location,
                url=card.canonical_url,
                in_list=uj is not None,
                user_job_id=uj.id if uj else None,
                status=uj.status if uj else None,
                score=m.score if m else None,
                band=m.band if m else None,
                why=None
                if uj is not None
                else why_not(card, who) or "Fits your profile but isn't in your list yet",
                new=started is not None and seen >= started,
                first_seen_at=seen,
            )
        )
    items.sort(key=lambda i: (not i.new, not i.in_list, -(i.score or 0), i.title.lower()))
    kept = sum(1 for i in items if i.in_list)
    return CompanyJobsOut(
        company=followed.name or (items[0].company if items else None) or "Company",
        checked_at=checked,
        items=items,
        total=len(items),
        new=sum(1 for i in items if i.new),
        in_list=kept,
        left_out=len(items) - kept,
    )


@router.post(
    "/companies/{employer_id}/jobs/{job_id}", response_model=RunJobOut, status_code=status.HTTP_201_CREATED
)
async def add_company_job(employer_id: UUID, job_id: UUID, user: Admin, db: UserDB):
    """Add an open job at a company you follow to your list anyway. It is scored like any other job."""
    _followed, _data, catalog = await _company(db, employer_id)
    if job_id not in catalog.values():
        raise NotFound("Job at this company")
    return await _add_job(db, user.id, job_id, "company_feed", "a followed company")


# --- Jobs -> From sources: every job the sources brought you, the last run's and older (user, 2026-11-17) --------

MAX_FROM_SOURCES = 1000
MAX_RUN_LINES = 2000
FITS = "Fits your profile but isn't in your list yet"


async def _source_verdicts(db) -> dict[UUID, tuple[str | None, UUID | None, datetime]]:
    """Each job the sources brought this user, newest run first: job id -> (why it was left out, employer, when)."""
    runs = await db.scalars(
        select(SourceRun)
        .where(SourceRun.source.in_(("company_feed", "adzuna")), SourceRun.error.is_(None))
        .order_by(SourceRun.ran_at.desc())
        .limit(MAX_RUN_LINES)
    )
    out: dict[UUID, tuple[str | None, UUID | None, datetime]] = {}
    for run in runs:
        for j in run.jobs or []:
            out.setdefault(UUID(j["job_id"]), (j.get("why"), run.employer_id, run.ran_at))
    return out


@router.get("/jobs", response_model=SourceJobsOut)
async def source_jobs(user: User, db: UserDB):
    """Every open job the job sources brought you: the last run's first, then older ones. The ones that fit are
    in your list already (with their score); the others say why they were left out, and can be added."""
    verdicts = await _source_verdicts(db)
    last = await _run_jobs(db)
    fresh = set(last[1]) if last else set()
    ids = list(verdicts)[: MAX_FROM_SOURCES * 2]
    catalog = {j.id: j for j in await db.scalars(select(Job).where(Job.id.in_(ids)))} if ids else {}
    mine = (
        {
            uj.job_id: (uj, m)
            for uj, m in (
                await db.execute(
                    select(UserJob, JobMatch)
                    .outerjoin(JobMatch, JobMatch.user_job_id == UserJob.id)
                    .where(UserJob.job_id.in_(ids))
                )
            ).all()
        }
        if ids
        else {}
    )
    urls: dict[UUID, str] = {}
    if ids:
        for job_id, url in (
            await db.execute(
                select(JobSource.job_id, JobSource.url).where(
                    JobSource.job_id.in_(ids), JobSource.url.is_not(None)
                )
            )
        ).all():
            urls.setdefault(job_id, url)
    items = []
    for job_id in ids:
        job = catalog.get(job_id)
        if job is None or (job.details or {}).get("closed_on_site"):
            continue  # taken down by the employer
        why, _employer, seen = verdicts[job_id]
        uj, m = mine.get(job_id, (None, None))
        items.append(
            CompanyJobOut(
                job_id=job_id,
                title=job.title,
                company=job.company,
                location=job.location,
                url=urls.get(job_id),
                in_list=uj is not None,
                user_job_id=uj.id if uj else None,
                status=uj.status if uj else None,
                score=m.score if m else None,
                band=m.band if m else None,
                why=None if uj is not None else why or FITS,
                new=job_id in fresh,
                first_seen_at=seen,
            )
        )
        if len(items) >= MAX_FROM_SOURCES:
            break
    items.sort(key=lambda i: (not i.new, -i.first_seen_at.timestamp(), not i.in_list, i.title.lower()))
    kept = sum(1 for i in items if i.in_list)
    return SourceJobsOut(
        ran_at=last[0] if last else None,
        items=items,
        total=len(items),
        new=sum(1 for i in items if i.new),
        in_list=kept,
        left_out=len(items) - kept,
    )


@router.post("/jobs/{job_id}", response_model=RunJobOut, status_code=status.HTTP_201_CREATED)
async def add_source_job(job_id: UUID, user: User, db: UserDB):
    """Add a job the sources brought you (and left out) to your list. It is scored like any other job."""
    verdicts = await _source_verdicts(db)
    if job_id not in verdicts:
        raise NotFound("Job from your sources")
    _why, employer, _seen = verdicts[job_id]
    return await _add_job(
        db, user.id, job_id, "company_feed" if employer else "job_board", "your job sources"
    )
