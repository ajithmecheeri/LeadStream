"""The app's side of the Job Search Service: pulling its event feed into the catalog and to the users the jobs
fit, sending the aggregated demand, checking a user's followed employers, and the one-time export of the old
company feeds.

What reaches a user is decided here, as before (relevance.py): a followed employer's jobs reach its followers at
their level and field; job-API jobs (no employer) reach every user whose search profiles they pass. HTTP
happens outside database transactions.
"""

import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, tuple_

from app.core.db import sessionmaker, user_scope
from app.modules.candidate.models import CandidateProfile
from app.modules.catalog.models import Job, JobSource
from app.modules.catalog.parsers import JobCard
from app.modules.catalog.service import CatalogMatch, upsert_cards
from app.modules.jobs.linking import link_cards
from app.modules.jobs.models import UserJob
from app.modules.matching import taxonomy
from app.modules.matching.service import queue_scoring
from app.modules.profiles.models import SearchProfile
from app.modules.sources import client
from app.modules.sources.models import CompanyFeed, JobSearchSync, PlatformCompany, SourceRun, WatchedCompany
from app.modules.sources.relevance import Audience, audience, why_not
from app.modules.users.models import User

log = logging.getLogger("fitfirst.sources")

PAGE = 500
MAX_PAGES = 20  # per pull; the rest follows on the next one (every 5 minutes)
DEMAND_EVERY = timedelta(hours=24)  # resent daily even when unchanged


# --- Listings as catalog cards -----------------------------------------------------------------------------


def card_of(listing: dict) -> JobCard | None:
    """A service listing as the catalog's JobCard (its first source names it)."""
    sources = listing.get("sources") or []
    if not sources:
        return None
    src = sources[0]
    return JobCard(
        source=src["source"],
        source_job_id=src["source_job_id"],
        title=listing["title"],
        company=listing.get("company"),
        location=listing.get("location"),
        lead="company_feed" if listing.get("employer_id") else "job_board",
        canonical_url=src.get("url"),
        work_model=listing.get("work_model"),
        salary=listing.get("salary"),
        experience=listing.get("experience"),
        skills=tuple(listing.get("skills") or ()),
        description=listing.get("description"),
        details={k: str(v) for k, v in (listing.get("details") or {}).items()},
        posted_at=datetime.fromisoformat(listing["posted_at"]) if listing.get("posted_at") else None,
    )


async def _refresh_job(job_id: UUID, card: JobCard) -> None:
    """An UPDATED listing: the employer's own wording replaces the catalog's (the catalog itself never overwrites
    a known description)."""
    async with sessionmaker()() as db, db.begin():
        job = await db.get(Job, job_id)
        if job is None:
            return
        for name in ("title", "location", "work_model", "salary", "experience"):
            if getattr(card, name):
                setattr(job, name, getattr(card, name))
        if card.description:
            job.description, job.description_complete = card.description, True


async def _mark_closed(listing: dict) -> None:
    """The employer took the job down: noted on the catalog job (decision 6; users' rows are left alone)."""
    card = card_of(listing)
    if card is None:
        return
    async with sessionmaker()() as db, db.begin():
        job = await db.scalar(
            select(Job)
            .join(JobSource, JobSource.job_id == Job.id)
            .where(JobSource.source == card.source, JobSource.source_job_id == card.source_job_id)
        )
        if job is not None:
            closed = listing.get("closed_at") or datetime.now(UTC).isoformat()
            job.details = {**(job.details or {}), "closed_on_site": closed[:10]}


# --- Who gets what -----------------------------------------------------------------------------------------


@dataclass
class Reader:
    user_id: UUID
    who: Audience
    follows: set[UUID]


@dataclass
class Arrived:
    """One listing that came in, stored in the catalog."""

    card: JobCard
    match: CatalogMatch
    employer_id: UUID | None
    updated: bool


@dataclass
class PullSummary:
    events: int = 0
    stored: int = 0
    new: int = 0  # jobs the catalog had not seen
    updated: int = 0  # known jobs the employer changed or reposted
    closed: int = 0
    added: dict[UUID, int] = field(default_factory=dict)  # per user
    runs: set[tuple[UUID, UUID | None]] = field(default_factory=set)  # (user, employer) with a run recorded


async def platform_ids() -> list[UUID]:
    """The shared list of companies the admins keep (user, 2026-11-17): read for every user."""
    async with sessionmaker()() as db:
        return list(await db.scalars(select(PlatformCompany.employer_id)))


async def readers() -> list[Reader]:
    async with sessionmaker()() as db:
        ids = list(await db.scalars(select(User.id).where(User.status == "active").order_by(User.created_at)))
    follows = set(await platform_ids())
    out = []
    for uid in ids:
        async with user_scope(uid) as db:
            out.append(Reader(uid, await audience(db, uid), follows))
    return out


async def seekers_with_profiles() -> list[UUID]:
    """Active users with a search profile: the ones whose open jobs at a newly followed company are caught up
    (a user without one gets every company's jobs when their first Skill Match profile is made)."""
    async with sessionmaker()() as db:
        ids = list(await db.scalars(select(User.id).where(User.status == "active")))
    out = []
    for uid in ids:
        async with user_scope(uid) as db:
            if await db.scalar(select(SearchProfile.id).where(SearchProfile.active).limit(1)):
                out.append(uid)
    return out


def _reaches(a: Arrived, r: Reader) -> str | bool:
    """ "" (kept) or why it was left out, when the listing is for this reader to judge (follower, or a job-API
    job and the reader has search profiles); False when it isn't theirs at all."""
    if a.employer_id is not None:
        if a.employer_id not in r.follows:
            return False
    elif not r.who.queries:
        return False
    return why_not(a.card, r.who) or ""


MAX_RUN_JOBS = 300  # jobs kept per run line for Job sources → Last run


async def _deliver(arrived: list[Arrived], people: list[Reader], summary: PullSummary) -> None:
    for r in people:
        keep: list[Arrived] = []
        per_source: dict[UUID | None, list[int]] = defaultdict(lambda: [0, 0])  # employer → [found, kept]
        listed: dict[UUID | None, list[dict]] = defaultdict(list)  # employer → the run's jobs and verdicts
        for a in arrived:
            verdict = _reaches(a, r)
            if verdict is False:
                continue
            per_source[a.employer_id][0] += 1
            listed[a.employer_id].append({"job_id": str(a.match.job_id), "why": verdict or None})
            if verdict == "":
                keep.append(a)
                per_source[a.employer_id][1] += 1
        if not per_source:
            continue
        async with user_scope(r.user_id) as db:
            had = set(
                await db.scalars(
                    select(UserJob.job_id).where(UserJob.job_id.in_([a.match.job_id for a in keep]))
                )
            )
            added = (
                await link_cards(db, r.user_id, [a.card for a in keep], [a.match for a in keep])
                if keep
                else []
            )
            changed = [a.match.job_id for a in keep if a.updated and a.match.job_id in had]
            rescore = list(added)
            if changed:
                rescore += list(await db.scalars(select(UserJob.id).where(UserJob.job_id.in_(changed))))
            for employer_id, (found, kept) in per_source.items():
                linked_new = len(
                    {
                        a.match.job_id
                        for a in keep
                        if a.employer_id == employer_id and a.match.job_id not in had
                    }
                )
                db.add(
                    SourceRun(
                        user_id=r.user_id,
                        source="company_feed" if employer_id else "adzuna",
                        employer_id=employer_id,
                        found=found,
                        added=linked_new,
                        skipped=found - kept,
                        jobs=listed[employer_id][:MAX_RUN_JOBS],
                    )
                )
                summary.runs.add((r.user_id, employer_id))
        if rescore:
            await queue_scoring(r.user_id, "jobs from the job search service", user_job_ids=rescore, delay=0)
        summary.added[r.user_id] = summary.added.get(r.user_id, 0) + len(added)


async def _store(events: list[dict], summary: PullSummary) -> list[Arrived]:
    """Each listing once (its latest event), active ones into the catalog, closed ones marked."""
    latest: dict[str, dict] = {}
    for e in events:
        latest[e["listing"]["listing_id"]] = e
    live, cards = [], []
    for e in latest.values():
        listing = e["listing"]
        if e["type"] == "CLOSED" or listing.get("status") == "closed":
            await _mark_closed(listing)
            summary.closed += 1
            continue
        card = card_of(listing)
        if card is not None:
            live.append(e)
            cards.append(card)
    if not cards:
        return []
    async with sessionmaker()() as db, db.begin():
        matches = await upsert_cards(db, cards)
    arrived = []
    for e, card, match in zip(live, cards, matches, strict=True):
        updated = e["type"] in ("UPDATED", "REPOSTED") and not match.created
        if updated:
            await _refresh_job(match.job_id, card)
        employer = e["listing"].get("employer_id")
        arrived.append(Arrived(card, match, UUID(employer) if employer else None, updated))
        summary.new += match.created
        summary.updated += updated
    summary.stored += len(arrived)
    return arrived


async def _sync_row(db) -> JobSearchSync:
    row = await db.get(JobSearchSync, 1)
    if row is None:
        row = JobSearchSync(id=1, cursor=0)
        db.add(row)
        await db.flush()
    return row


async def pull(js: client.JobSearch) -> PullSummary:
    """Read the event feed from the saved cursor and deliver what arrived. Safe to repeat: catalog and links
    are idempotent, and the cursor moves only after a page is delivered."""
    summary = PullSummary()
    started = datetime.now(UTC)
    await export_legacy(js)
    async with sessionmaker()() as db:
        cursor = (await _sync_row(db)).cursor
        await db.commit()
    people: list[Reader] | None = None
    for _ in range(MAX_PAGES):
        page = await js.events(after=cursor, limit=PAGE)
        events = page.get("events") or []
        if not events:
            break
        summary.events += len(events)
        arrived = await _store(events, summary)
        if arrived:
            people = people if people is not None else await readers()
            await _deliver(arrived, people, summary)
        cursor = page["next_cursor"]
        async with sessionmaker()() as db, db.begin():
            row = await _sync_row(db)
            row.cursor = cursor
        if len(events) < PAGE:
            break
    async with sessionmaker()() as db, db.begin():
        row = await _sync_row(db)
        row.pulled_at, row.last_error = datetime.now(UTC), None
        if summary.stored or summary.closed:  # the last run that brought something, for Job sources
            row.last_pull_started_at, row.last_pull_at = started, row.pulled_at
            row.last_pull_jobs, row.last_pull_new = summary.stored, summary.new
            row.last_pull_updated, row.last_pull_closed = summary.updated, summary.closed
    if summary.events:
        log.info(
            "pulled %d events: %d jobs, %d closed, %d new for users",
            summary.events,
            summary.stored,
            summary.closed,
            sum(summary.added.values()),
        )
    return summary


async def note_error(message: str) -> None:
    async with sessionmaker()() as db, db.begin():
        (await _sync_row(db)).last_error = message[:500]


# --- Demand: what users want, aggregated ---------------------------------------------------------------------


async def demand() -> list[dict]:
    """Search areas across active users: (location, role family) with example titles. No user ids, no counts."""
    areas: dict[tuple[str, str], tuple[str, list[str]]] = {}
    async with sessionmaker()() as db:
        ids = list(await db.scalars(select(User.id).where(User.status == "active")))
    for uid in ids:
        async with user_scope(uid) as db:
            cand = await db.get(CandidateProfile, uid)
            profiles = list(await db.scalars(select(SearchProfile).where(SearchProfile.active)))
        fallback = list(cand.job_locations or []) if cand else []
        for p in profiles:
            for loc in p.locations or fallback:
                location = " ".join(loc.split())
                if not location:
                    continue
                for role in p.target_roles:
                    for family in sorted(taxonomy.title_families(role) or {"other"}):
                        _, titles = areas.setdefault((location.lower(), family), (location, []))
                        if role not in titles and len(titles) < 20:
                            titles.append(role)
    return [
        {"location": loc, "role_family": family, "titles": titles}
        for (_, family), (loc, titles) in sorted(areas.items())
    ]


async def push_demand(js: client.JobSearch, force: bool = False) -> bool:
    """Send the search areas when they changed (or daily). True when sent."""
    areas = await demand()
    digest = hashlib.sha256(json.dumps(areas, sort_keys=True).encode()).hexdigest()
    async with sessionmaker()() as db:
        row = await _sync_row(db)
        same = (
            row.demand_hash == digest and row.pushed_at and datetime.now(UTC) - row.pushed_at < DEMAND_EVERY
        )
        await db.commit()
    if same and not force:
        return False
    await js.put_demand(areas)
    async with sessionmaker()() as db, db.begin():
        row = await _sync_row(db)
        row.demand_hash, row.pushed_at = digest, datetime.now(UTC)
    return True


# --- The old company feeds, exported once ---------------------------------------------------------------------


async def export_legacy(js: client.JobSearch) -> int:
    """Send each company feed the app used to read itself to the service, with the same id (decision 8)."""
    async with sessionmaker()() as db:
        feeds = list(await db.scalars(select(CompanyFeed).where(CompanyFeed.exported_at.is_(None))))
    for f in feeds:
        out = await js.register(name=f.name, system=f.ats, board=f.board, employer_id=f.id)
        if UUID(out["id"]) != f.id:  # the service already had this board under another id
            log.warning(
                "company feed %s (%s/%s) is employer %s in the service", f.id, f.ats, f.board, out["id"]
            )
            await _repoint(f.id, UUID(out["id"]))
        async with sessionmaker()() as db, db.begin():
            row = await db.get(CompanyFeed, f.id)
            row.exported_at = datetime.now(UTC)
    if feeds:
        log.info("exported %d company feeds to the job search service", len(feeds))
    return len(feeds)


async def _repoint(old: UUID, new: UUID) -> None:
    async with sessionmaker()() as db, db.begin():
        ids = list(await db.scalars(select(User.id)))
        shared = await db.get(PlatformCompany, old)
        if shared is not None and await db.get(PlatformCompany, new) is None:
            db.add(PlatformCompany(employer_id=new, name=shared.name, added_by=shared.added_by))
        if shared is not None:
            await db.delete(shared)
    for uid in ids:
        async with user_scope(uid) as db:
            for w in await db.scalars(select(WatchedCompany).where(WatchedCompany.employer_id == old)):
                w.employer_id = new
            for r in await db.scalars(select(SourceRun).where(SourceRun.employer_id == old)):
                r.employer_id = new


# --- A user's "check now" ------------------------------------------------------------------------------------


async def check_user(
    js: client.JobSearch, user_id: UUID, employer_ids: list[UUID] | None = None
) -> PullSummary:
    """Check the shared list's employers (or just `employer_ids`, newly followed) now, then pull what changed.
    An employer that brought nothing new still gets a run line, so the page shows it was checked. The open jobs
    of newly followed employers are caught up for every user with a search profile; a full check catches up the
    admin who asked."""
    ids = await platform_ids()
    if employer_ids is not None:
        wanted = set(employer_ids)
        ids = [e for e in ids if e in wanted]
    results: dict[UUID, dict | str | None] = {}
    for eid in ids:
        try:
            results[eid] = await js.check(eid)
        except client.Refused as e:
            results[eid] = e.message
    summary = await pull(js)
    for eid, run in results.items():
        if isinstance(run, str) or (run and run.get("error")):
            if (user_id, eid) not in summary.runs:
                async with user_scope(user_id) as db:
                    error = run if isinstance(run, str) else run["error"]
                    db.add(SourceRun(user_id=user_id, source="company_feed", employer_id=eid, error=error))
            continue
        people = [user_id]
        if employer_ids is not None:
            people += [u for u in await seekers_with_profiles() if u != user_id]
        for uid in people:
            added = await catch_up(js, uid, eid)
            summary.added[uid] = summary.added.get(uid, 0) + added
    return summary


async def catch_up_all(js: client.JobSearch, user_id: UUID) -> int:
    """Every shared company's open jobs for one user (their first Skill Match profile was just made)."""
    return sum([await catch_up(js, user_id, eid) for eid in await platform_ids()])


async def catalog_ids(db, listings: list[dict]) -> dict[str, UUID]:
    """Each service listing's catalog job (listing id → job id); a listing still on its way through the event
    feed has none yet."""
    keys = {}
    for listing in listings:
        card = card_of(listing)
        if card is not None:
            keys[(card.source, card.source_job_id)] = listing["listing_id"]
    out: dict[str, UUID] = {}
    if keys:
        rows = await db.execute(
            select(JobSource.source, JobSource.source_job_id, JobSource.job_id).where(
                tuple_(JobSource.source, JobSource.source_job_id).in_(list(keys))
            )
        )
        for source, source_job_id, job_id in rows.all():
            out[keys[(source, source_job_id)]] = job_id
    return out


async def catch_up(js: client.JobSearch, user_id: UUID, employer_id: UUID) -> int:
    """The open jobs a followed employer already had that fit the user, into their list (2026-11-16: the event
    feed brings only what changes, so jobs open before the user followed never reached them). Jobs already in
    the list, whatever their status, are left alone. Writes the employer's check line: open jobs in India, added,
    left out. Returns how many were added."""
    try:
        data = await js.listings(employer_id)
    except (client.Unavailable, client.Refused) as e:
        log.warning("catch-up of %s skipped: %s", employer_id, e)
        return 0
    listings = data.get("listings") or []
    async with user_scope(user_id) as db:
        catalog = await catalog_ids(db, listings)
        mine = set(await db.scalars(select(UserJob.job_id).where(UserJob.job_id.in_(list(catalog.values())))))
        who = await audience(db, user_id)
        cards, matches, left_out = [], [], 0
        listed: list[dict] = []  # every open job and its verdict, for Jobs -> From sources
        for listing in listings:
            card = card_of(listing)
            job_id = catalog.get(listing["listing_id"])
            if card is None or job_id is None:
                continue
            why = why_not(card, who)
            if len(listed) < MAX_RUN_JOBS:
                listed.append({"job_id": str(job_id), "why": why or None})
            if job_id in mine:
                continue
            if why:
                left_out += 1
            else:
                cards.append(card)
                matches.append(CatalogMatch(job_id=job_id, created=False))
        added = await link_cards(db, user_id, cards, matches) if cards else []
        db.add(
            SourceRun(
                user_id=user_id,
                source="company_feed",
                employer_id=employer_id,
                found=len(listings),
                added=len(added),
                skipped=left_out,
                jobs=listed,
            )
        )
    if added:
        await queue_scoring(user_id, "open jobs at a company you follow", user_job_ids=added, delay=0)
    return len(added)
