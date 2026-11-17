"""The shared job catalog: each posting is stored once, however many users and portals it arrives from.

A card matches an existing job, in order of confidence, by:
  1. the same portal listing: (source, source_job_id)
  2. the same public URL
  3. the same fingerprint: normalised company | title | location (not when the company is unknown or cut off)
A match is merged (missing facts filled in, a full description beats a partial one) and gains a source row;
no match creates a job. The catalog holds public posting data only: nothing about the recipient.

Cards from a hand-forwarded alert are unverified: the portal's DKIM signature is gone, so the forwarder could
have edited them. An unverified card never changes an existing job; with no match it creates one marked
unverified, and the first verified card for that job replaces its facts.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.models import Job, JobSource
from app.modules.catalog.parsers import JobCard
from app.modules.catalog.parsers.normalize import fingerprint

_FILL_IF_MISSING = ("location", "work_model", "experience", "salary")


@dataclass(frozen=True)
class CatalogMatch:
    job_id: UUID
    created: bool


def card_fingerprint(card: JobCard) -> str | None:
    return None if card.company_truncated else fingerprint(card.company, card.title, card.location)


def _lock_keys(card: JobCard) -> list[str]:
    keys = [f"src:{card.source}:{card.source_job_id}"]
    if fp := card_fingerprint(card):
        keys.append(f"fp:{fp}")
    return keys


async def upsert_cards(db: AsyncSession, cards: list[JobCard], verified: bool = True) -> list[CatalogMatch]:
    """Store the cards in the catalog; one CatalogMatch per card, in order. Safe to repeat.

    Two workers can parse alerts listing the same job at the same moment. Transaction-scoped advisory
    locks on each card's identity keys, taken in sorted order (no deadlocks), make the second one wait and
    then find the first one's job instead of creating a duplicate.
    """
    for key in sorted({k for card in cards for k in _lock_keys(card)}):
        await db.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": key})
    return [await _upsert(db, card, verified) for card in cards]


def _facts(card: JobCard) -> dict:
    return dict(
        title=card.title,
        company=card.company,
        location=card.location,
        work_model=card.work_model,
        experience=card.experience,
        salary=card.salary,
        skills=list(card.skills),
        description=card.description,
        description_complete=bool(card.description),
        details=_public_details(card),
        posted_at=card.posted_at,
    )


async def _upsert(db: AsyncSession, card: JobCard, verified: bool) -> CatalogMatch:
    fp = card_fingerprint(card)
    job = await _find(db, card, fp)
    created = job is None
    if job is None:
        job = Job(fingerprint=fp, verified=verified, **_facts(card))
        db.add(job)
        await db.flush()
    elif not verified:
        return CatalogMatch(job.id, False)  # link the user to it, change nothing
    elif not job.verified:
        await _replace(db, job, card, fp)
    else:
        await _merge(db, job, card, fp)
    await db.execute(
        insert(JobSource)
        .values(job_id=job.id, source=card.source, source_job_id=card.source_job_id, url=card.canonical_url)
        .on_conflict_do_nothing()
    )
    return CatalogMatch(job.id, created)


async def _find(db: AsyncSession, card: JobCard, fp: str | None) -> Job | None:
    by_listing = (
        select(Job)
        .join(JobSource, JobSource.job_id == Job.id)
        .where(JobSource.source == card.source, JobSource.source_job_id == card.source_job_id)
    )
    queries = [by_listing]
    if card.canonical_url:
        queries.append(
            select(Job).join(JobSource, JobSource.job_id == Job.id).where(JobSource.url == card.canonical_url)
        )
    if fp:
        queries.append(select(Job).where(Job.fingerprint == fp))
    for q in queries:
        job = (await db.execute(q.limit(1))).scalar_one_or_none()
        if job is not None:
            return job
    return None


def _public_details(card: JobCard) -> dict:
    return {**card.details, **({"company_truncated": True} if card.company_truncated else {})}


async def _replace(db: AsyncSession, job: Job, card: JobCard, fp: str | None) -> None:
    """A verified card for a job only hand forwards have described: its facts win over theirs."""
    for name, value in _facts(card).items():
        setattr(job, name, value)
    job.verified = True
    if fp != job.fingerprint:
        taken = (
            fp and (await db.execute(select(Job.id).where(Job.fingerprint == fp, Job.id != job.id))).first()
        )
        job.fingerprint = None if taken else fp
    await db.flush()


async def _merge(db: AsyncSession, job: Job, card: JobCard, fp: str | None) -> None:
    """Fill in what the catalog doesn't know yet; never overwrite a known fact with a weaker one."""
    details = dict(job.details or {})
    if (
        card.company
        and not card.company_truncated
        and (job.company is None or details.get("company_truncated"))
    ):
        job.company = card.company
        details.pop("company_truncated", None)
    elif job.company is None and card.company:
        job.company = card.company
        details["company_truncated"] = True
    for name in (*_FILL_IF_MISSING, "posted_at"):
        if getattr(job, name) is None and getattr(card, name):
            setattr(job, name, getattr(card, name))
    known = {s.lower() for s in job.skills or []}
    job.skills = [*(job.skills or []), *(s for s in card.skills if s.lower() not in known)]
    if card.description and not job.description_complete:
        job.description, job.description_complete = card.description, True
    job.details = {**card.details, **details}  # what the catalog already has wins
    # A job first seen without a usable fingerprint (e.g. a cut-off company) takes one when it's free.
    if fp and job.fingerprint is None:
        taken = (await db.execute(select(Job.id).where(Job.fingerprint == fp))).first()
        if not taken:
            job.fingerprint = fp
    await db.flush()
