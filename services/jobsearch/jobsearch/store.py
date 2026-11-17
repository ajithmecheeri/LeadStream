"""The listings store: what a connector read becomes listings, versions and events.

Change and repost detection (docs/jobsearch-plan-discovery.md, section 8):
  - a posting not seen before → NEW (a Workday posting waits as `pending` until its details are read);
  - the same posting (or the same requisition at that employer) with different content → UPDATED, the earlier
    content kept in listing_versions;
  - a closed listing seen again, or its requisition reposted under a new id → REPOSTED;
  - missing from its board on two complete reads in a row → CLOSED.
A known fact is never replaced by an empty one (a details call that failed once doesn't count as a change).
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch.config import get_settings
from jobsearch.connectors import BoardResult, Posting
from jobsearch.db import lock_events
from jobsearch.models import BoardPage, Employer, EmployerBoard, Event, Listing, ListingSource, ListingVersion

CLOSE_AFTER_MISSES = 2
_CONTENT = (
    "title",
    "company",
    "location",
    "work_model",
    "experience",
    "salary",
    "description",
    "requisition_id",
)


@dataclass
class Counts:
    found: int = 0
    new: int = 0
    updated: int = 0
    reposted: int = 0
    closed: int = 0
    pending: int = 0
    events: list[tuple[str, UUID]] = field(default_factory=list)


def content_hash(values: dict) -> str:
    raw = "\x1f".join(str(values.get(k) or "") for k in _CONTENT)
    return hashlib.sha256(raw.encode()).hexdigest()


def _values(p: Posting) -> dict:
    return {
        "title": p.title,
        "company": p.company,
        "location": p.location,
        "work_model": p.work_model,
        "experience": p.experience,
        "salary": p.salary,
        "description": p.description,
        "requisition_id": p.requisition_id,
        "skills": list(p.skills),
        "details": dict(p.details),
        "posted_at": p.posted_at,
    }


def _merged(listing: Listing, p: Posting) -> dict:
    """The posting's values, keeping the listing's known ones where the posting has none."""
    out = {}
    for k, v in _values(p).items():
        old = getattr(listing, k)
        out[k] = v if v not in (None, "", [], {}) else old
    return out


def snapshot(listing: Listing) -> dict:
    return {
        **{k: getattr(listing, k) for k in _CONTENT},
        "skills": list(listing.skills or []),
        "details": dict(listing.details or {}),
        "posted_at": listing.posted_at.isoformat() if listing.posted_at else None,
        "version": listing.version,
    }


class _Run:
    def __init__(self, db: AsyncSession, employer: Employer | None, board: EmployerBoard | None):
        self.db, self.employer, self.board = db, employer, board
        self.now = datetime.now(UTC)
        self.counts = Counts()
        self.seen: set[UUID] = set()
        self.announced: set[UUID] = set()  # one event per listing per run

    def event(self, kind: str, listing: Listing) -> None:
        if listing.id in self.announced:
            return
        self.announced.add(listing.id)
        self.db.add(Event(type=kind, listing_id=listing.id, occurred_at=self.now))
        self.counts.events.append((kind, listing.id))
        attr = kind.lower()  # new | updated | reposted
        setattr(self.counts, attr, getattr(self.counts, attr) + 1)

    def _seen(self, listing: Listing) -> None:
        self.seen.add(listing.id)
        listing.last_seen_at = self.now
        listing.missed_checks = 0

    def _apply(self, listing: Listing, values: dict) -> bool:
        """Set the values; True when the content changed (the old content is kept as a version)."""
        new_hash = content_hash(values)
        if new_hash == listing.content_hash:
            for k in ("skills", "details", "posted_at"):  # not part of the hash; refresh quietly
                setattr(listing, k, values[k])
            return False
        self.db.add(
            ListingVersion(listing_id=listing.id, version=listing.version, snapshot=snapshot(listing))
        )
        for k, v in values.items():
            setattr(listing, k, v)
        listing.content_hash = new_hash
        listing.version += 1
        return True

    async def _source(self, listing: Listing, p: Posting) -> None:
        self.db.add(
            ListingSource(
                listing_id=listing.id,
                source=p.source,
                source_job_id=p.source_job_id,
                url=p.url,
                apply_url=p.apply_url,
            )
        )

    async def _by_requisition(self, p: Posting) -> Listing | None:
        if not (p.requisition_id and self.employer):
            return None
        return await self.db.scalar(
            select(Listing)
            .where(
                Listing.employer_id == self.employer.id,
                Listing.requisition_id == p.requisition_id,
                Listing.title == p.title,
            )
            .order_by(Listing.last_seen_at.desc())
            .limit(1)
        )

    async def posting(self, p: Posting, listing: Listing | None) -> None:
        self.counts.found += 1
        if listing is None and (listing := await self._by_requisition(p)) is not None:
            await self._source(listing, p)  # the same requisition under a new id
        if listing is None and not p.title:
            return  # a presence-only stub for a listing that no longer exists here: nothing to add
        if listing is None:
            values = _values(p)
            listing = Listing(
                employer_id=self.employer.id if self.employer else None,
                board_id=self.board.id if self.board else None,
                status="pending" if p.needs_details else "active",
                content_hash=content_hash(values),
                first_seen_at=self.now,
                last_seen_at=self.now,
                **values,
            )
            self.db.add(listing)
            await self.db.flush()
            await self._source(listing, p)
            self._seen(listing)
            if p.needs_details:
                self.counts.pending += 1
            else:
                self.event("NEW", listing)
            return

        self._seen(listing)
        changed = False if p.needs_details else self._apply(listing, _merged(listing, p))
        if listing.status == "closed":
            listing.status, listing.closed_at = "active", None
            self.event("REPOSTED", listing)
        elif listing.status == "pending":
            if p.needs_details:
                self.counts.pending += 1
            else:
                listing.status = "active"
                self.event("NEW", listing)
        elif changed:
            self.event("UPDATED", listing)

    async def close_missing(self) -> None:
        """Active listings of the board that this complete read didn't see: closed on the second miss."""
        if self.board is None:
            return
        rows = await self.db.scalars(
            select(Listing).where(Listing.board_id == self.board.id, Listing.status == "active")
        )
        for listing in rows:
            if listing.id in self.seen:
                continue
            listing.missed_checks += 1
            if listing.missed_checks >= CLOSE_AFTER_MISSES:
                listing.status, listing.closed_at = "closed", self.now
                self.db.add(Event(type="CLOSED", listing_id=listing.id, occurred_at=self.now))
                self.counts.events.append(("CLOSED", listing.id))
                self.counts.closed += 1


async def _existing(db: AsyncSession, postings: list[Posting]) -> dict[tuple[str, str], Listing]:
    keys = {(p.source, p.source_job_id) for p in postings}
    if not keys:
        return {}
    rows = await db.execute(
        select(ListingSource.source, ListingSource.source_job_id, Listing)
        .join(Listing, Listing.id == ListingSource.listing_id)
        .where(ListingSource.source_job_id.in_({k[1] for k in keys}))
    )
    return {(s, sid): listing for s, sid, listing in rows if (s, sid) in keys}


async def skipped_pages(db: AsyncSession, board: EmployerBoard) -> set[str]:
    """Careers pages found outside the service's country (or not a job) recently: not read again yet."""
    since = datetime.now(UTC) - timedelta(days=get_settings().careers_skip_days)
    rows = await db.scalars(
        select(BoardPage.page_id).where(BoardPage.board_id == board.id, BoardPage.checked_at >= since)
    )
    return set(rows)


async def remember_pages(db: AsyncSession, board: EmployerBoard, page_ids: tuple[str, ...]) -> None:
    if not page_ids:
        return
    now = datetime.now(UTC)
    await db.execute(
        insert(BoardPage)
        .values([{"board_id": board.id, "page_id": p, "checked_at": now} for p in dict.fromkeys(page_ids)])
        .on_conflict_do_update(
            index_elements=[BoardPage.board_id, BoardPage.page_id], set_={"checked_at": now}
        )
    )


async def known_ids(db: AsyncSession, board: EmployerBoard) -> set[str]:
    """Source ids of the board's postings whose details were read (not pending)."""
    rows = await db.scalars(
        select(ListingSource.source_job_id)
        .join(Listing, Listing.id == ListingSource.listing_id)
        .where(Listing.board_id == board.id, Listing.status != "pending")
    )
    return set(rows)


async def record_board(
    db: AsyncSession, employer: Employer, board: EmployerBoard, result: BoardResult
) -> Counts:
    """Store one read of a board, inside the caller's transaction."""
    await lock_events(db)
    run = _Run(db, employer, board)
    existing = await _existing(db, result.postings)
    for p in result.postings:
        await run.posting(p, existing.get((p.source, p.source_job_id)))
    if result.complete:
        await run.close_missing()
    board.last_checked_at, board.last_error = run.now, None
    board.jobs_total, board.jobs_in_scope = result.total, len(result.postings)
    return run.counts


async def record_search(db: AsyncSession, postings: list[Posting]) -> Counts:
    """Store what a job API returned for a search area (no board, so nothing is closed by absence)."""
    await lock_events(db)
    run = _Run(db, None, None)
    unique = list({(p.source, p.source_job_id): p for p in postings}.values())
    existing = await _existing(db, unique)
    for p in unique:
        await run.posting(p, existing.get((p.source, p.source_job_id)))
    return run.counts
