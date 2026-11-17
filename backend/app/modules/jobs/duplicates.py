"""Duplicates: one role arriving twice (decision 12 in docs/plan-m9.md, agreed with the user 2026-11-05).

The catalog already stores a posting once per listing, link or fingerprint. This finds the rest among one user's
jobs, and merges only when it's certain; otherwise the user decides:
- same: the same company, title (word for word once "VP" = "Vice President", "Sr" = "Senior"…) and city. The later
  job is merged into the earlier one; an applied job is always the one kept.
- likely: the same company with the same title in another city, a similar title at the same level in the same
  city, or a near-identical description. Kept, flagged, with Same job / Different job.
- agency: one poster is anonymous ("Leading MNC", "Confidential") or a recruitment agency, the other a named
  company, and the descriptions, city, level, experience and title all match. Kept, flagged. Once the user says
  Same job on such a pair, that agency's later postings are compared with that company's jobs without the
  description (it recruits for them: `_recruits`).
Two named companies are never compared (shared description templates are normal), and two listings on the same
company career feed are separate openings by definition. Descriptions alone never flag a job.

A merged job gets status 'duplicate' and `duplicate_of`: it leaves every list, count and alert, and "Not the same
job" brings it back. Answers are remembered per pair, so a pair is never asked about twice.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cached_property
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.catalog.models import Job, JobSource
from app.modules.catalog.parsers.base import COMPANY_SITES
from app.modules.jobs.models import LEAD_RANK, JobDuplicate, UserJob
from app.modules.matching import taxonomy
from app.modules.networking.companies import company_key, matches

FEEDS = COMPANY_SITES  # two listings on one company's careers site are separate openings
TITLE_CLOSE = 0.6  # share of title words in common (Jaccard) for "a similar title"
SAME_TEXT = 85  # % of the shorter description's 5-word phrases found in the other: near-identical
AGENCY_TEXT = 60  # an agency's copy of a company's description (they add their own lines)
MIN_TEXT = 300  # characters; shorter descriptions aren't compared

_ABBREVIATIONS = {
    "vp": "vice president", "svp": "senior vice president", "evp": "executive vice president",
    "avp": "assistant vice president", "sr": "senior", "snr": "senior", "jr": "junior", "mgr": "manager",
    "dir": "director", "eng": "engineering", "engg": "engineering", "gm": "general manager",
    "tpm": "technical program manager", "em": "engineering manager", "swe": "software engineer",
    "dev": "developer", "mgmt": "management", "ops": "operations", "principle": "principal",
}  # fmt: skip
_STOP = {"of", "the", "and", "for", "in", "a", "an", "at", "to", "with"}
# Words that change the level: "Engineering Manager" is not "Senior Engineering Manager".
_RANK = {
    "senior", "junior", "lead", "principal", "staff", "head", "chief", "associate", "assistant", "deputy", "vice",
    "president", "executive", "general", "group", "intern", "trainee", "i", "ii", "iii", "iv", "1", "2", "3", "4",
}  # fmt: skip
_UNNAMED = re.compile(
    r"^(confidential|undisclosed|stealth|mnc|hiring company|our client|client|company"
    r"|(a |an )?(leading|reputed|top|well known|large|global|renowned|prestigious|fortune \d+)( [a-z]+){0,3}"
    r" (mnc|company|firm|organization|organisation|client|bank|group|startup|brand|conglomerate))$"
)
_AGENCY = re.compile(
    r"\b(consultants|recruitment|recruiters|recruiting|staffing|placements?|manpower|executive search"
    r"|search partners|headhunt[a-z]*|talent solutions|hr services|hr solutions|job management)\b"
)


@dataclass(frozen=True)
class Found:
    kind: str  # same | likely | agency
    reason: str
    similarity: int | None


@dataclass
class View:
    """One of the user's jobs, as compared here."""

    id: UUID
    status: str
    first_seen_at: datetime
    title: str
    company: str | None
    location: str | None
    experience: str | None
    description: str | None
    sources: frozenset[str] = field(default_factory=frozenset)

    @cached_property
    def words(self) -> frozenset[str]:
        return title_words(self.title)

    @cached_property
    def cities(self) -> frozenset[str]:
        found, _ = taxonomy.cities(self.location)
        if not found and taxonomy.is_remote(self.location):
            found = {"remote"}
        if not found and self.location:
            found = {" ".join(re.sub(r"[^a-z0-9]+", " ", self.location.lower()).split())}
        return frozenset(found)

    @cached_property
    def level(self) -> int | None:
        return taxonomy.seniority(self.title)

    @cached_property
    def poster(self) -> str:
        return poster(self.company)

    @cached_property
    def phrases(self) -> frozenset[str]:
        return phrases(self.description)


def title_words(title: str | None) -> frozenset[str]:
    words = re.sub(r"[^a-z0-9]+", " ", (title or "").lower().replace("&", " and ")).split()
    expanded = " ".join(_ABBREVIATIONS.get(w, w) for w in words).split()
    return frozenset(w for w in expanded if w not in _STOP)


def poster(company: str | None) -> str:
    """'company', 'agency' (a recruitment firm's own name) or 'unnamed' ("Leading MNC", "Confidential")."""
    # The plain name: company_key would drop the "company" of "A Leading Fintech Company".
    key = " ".join(re.sub(r"[^a-z0-9]+", " ", (company or "").lower()).split())
    if not key or _UNNAMED.match(key):
        return "unnamed"
    return "agency" if _AGENCY.search(key) else "company"


def phrases(text: str | None) -> frozenset[str]:
    if not text or len(text) < MIN_TEXT:
        return frozenset()
    words = re.sub(r"[^a-z0-9]+", " ", taxonomy.without_boilerplate(text).lower()).split()
    return frozenset(" ".join(words[i : i + 5]) for i in range(len(words) - 4))


def similarity(a: View, b: View) -> int | None:
    """% of the shorter description's phrases found in the other; None unless both have a description."""
    if not a.phrases or not b.phrases:
        return None
    return round(100 * len(a.phrases & b.phrases) / min(len(a.phrases), len(b.phrases)))


def same_company(a: str | None, b: str | None) -> bool:
    ka, kb = company_key(a), company_key(b)
    return bool(ka and kb and (matches(a, {kb}) or matches(b, {ka})))


def titles_close(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b:
        return False
    if (a ^ b) & _RANK:
        return False  # "Senior" or "Lead" on one only: another level
    small, big = sorted((a, b), key=len)
    return (len(small) >= 2 and small <= big) or len(a & b) / len(a | b) >= TITLE_CLOSE


def _years(text: str | None) -> tuple[str, ...]:
    return tuple(re.findall(r"\d+", text or ""))


def _same_level(a: View, b: View) -> bool:
    return a.level is None or b.level is None or a.level == b.level


def _same_years(a: View, b: View) -> bool:
    ya, yb = _years(a.experience), _years(b.experience)
    return not ya or not yb or ya == yb


def classify(a: View, b: View, recruits: frozenset[tuple[str, str]] = frozenset()) -> Found | None:
    """Are these two of the user's jobs one role? None when there's no reason to think so.

    `recruits`: (agency, company) keys the user has confirmed before (Same job on an agency pair): that agency's
    postings are compared with the company's jobs on title, city, level and years, without the description."""
    if a.sources & b.sources & FEEDS:
        return None  # two listings on one company's careers site: separate openings
    sim = similarity(a, b)
    posters = {a.poster, b.poster}
    if posters == {"company"} or posters == {"agency"}:
        return _same_company(a, b, sim) if same_company(a.company, b.company) else None
    if "company" not in posters:
        return None  # two unnamed posters: nothing ties them together
    near = (
        bool(a.cities & b.cities)
        and _same_level(a, b)
        and _same_years(a, b)
        and titles_close(a.words, b.words)
    )
    if near and sim is not None and sim >= AGENCY_TEXT:
        return Found("agency", "Possibly the same role, posted by an agency", sim)
    agency, named = (a, b) if a.poster == "agency" else (b, a)
    if (
        near
        and agency.poster == "agency"
        and (company_key(agency.company), company_key(named.company)) in recruits
    ):
        return Found(
            "agency", f"{agency.company} recruits for {named.company} (you confirmed this before)", sim
        )
    return None


def _same_company(a: View, b: View, sim: int | None) -> Found | None:
    company = a.company or b.company
    same_city = a.cities == b.cities
    if a.words == b.words:
        if same_city and a.poster == "company":
            return Found("same", f"Same title at {company}, same city", sim)
        if same_city:
            return Found("likely", f"Same title from {company}, same city", sim)
        return Found("likely", f"Same title at {company}, another city", sim)
    nearby = not a.cities or not b.cities or bool(a.cities & b.cities)
    if not nearby or not _same_level(a, b):
        return None
    if titles_close(a.words, b.words):
        return Found("likely", f"A similar title at {company}, same city", sim)
    if sim is not None and sim >= SAME_TEXT and _same_years(a, b):
        return Found("likely", f"Almost the same description at {company}", sim)
    return None


async def _views(db: AsyncSession) -> list[View]:
    rows = (
        await db.execute(
            select(UserJob, Job).join(Job, Job.id == UserJob.job_id).where(UserJob.status != "duplicate")
        )
    ).all()
    sources: dict[UUID, set[str]] = {}
    job_ids = [job.id for _, job in rows]
    for job_id, source in (
        await db.execute(select(JobSource.job_id, JobSource.source).where(JobSource.job_id.in_(job_ids)))
    ).all():
        sources.setdefault(job_id, set()).add(source)
    return [
        View(
            id=uj.id,
            status=uj.status,
            first_seen_at=uj.first_seen_at,
            title=job.title,
            company=job.company,
            location=job.location,
            experience=job.experience,
            description=uj.description or job.description,
            sources=frozenset(sources.get(job.id, ())),
        )
        for uj, job in rows
    ]


async def check(db: AsyncSession, user_id: UUID, user_job_ids: list[UUID] | None = None) -> set[UUID]:
    """Compare these new jobs (None: all the user's jobs, oldest first) with the user's others. Certain duplicates
    are merged, possible ones recorded for the user to decide. Returns the ids merged into another job."""
    views = await _views(db)
    new = {v.id for v in views} if user_job_ids is None else set(user_job_ids)
    if not new:
        return set()
    known = {
        frozenset(p)
        for p in (await db.execute(select(JobDuplicate.user_job_id, JobDuplicate.other_id))).all()
    }
    recruits = await _recruits(db)
    pool = [v for v in views if v.id not in new]
    merged: set[UUID] = set()
    for v in sorted((v for v in views if v.id in new), key=lambda v: (v.first_seen_at, str(v.id))):
        found = [
            (o, f) for o in pool if frozenset((v.id, o.id)) not in known and (f := classify(v, o, recruits))
        ]
        same = next(((o, f) for o, f in found if f.kind == "same"), None)
        for o, f in [same] if same else found:
            db.add(
                JobDuplicate(
                    user_id=user_id,
                    user_job_id=v.id,
                    other_id=o.id,
                    kind=f.kind,
                    reason=f.reason,
                    similarity=f.similarity,
                )
            )
        await db.flush()
        if same and await merge(db, v.id, same[0].id) not in (None, v.id):
            merged.add(v.id)
            continue
        pool.append(v)
    return merged


async def _recruits(db: AsyncSession) -> frozenset[tuple[str, str]]:
    """(agency, company) keys from the user's earlier "Same job" answers on agency pairs: that agency recruits for
    that company. Worked out from the answered pairs, so "Not the same job" later takes it back."""
    one, two = aliased(UserJob), aliased(UserJob)
    ja, jb = aliased(Job), aliased(Job)
    rows = await db.execute(
        select(ja.company, jb.company)
        .select_from(JobDuplicate)
        .join(one, one.id == JobDuplicate.user_job_id)
        .join(two, two.id == JobDuplicate.other_id)
        .join(ja, ja.id == one.job_id)
        .join(jb, jb.id == two.job_id)
        .where(JobDuplicate.kind == "agency", JobDuplicate.answer == "same")
    )
    out = set()
    for a, b in rows:
        agency, named = (a, b) if poster(a) == "agency" else (b, a)
        if poster(agency) == "agency" and poster(named) == "company":
            out.add((company_key(agency), company_key(named)))
    return frozenset(out)


async def merge(db: AsyncSession, one_id: UUID, two_id: UUID) -> UUID | None:
    """Merge two of the user's jobs into one. Returns the id kept: the applied one, else the earlier one. None
    when both are applied (both stay: each has its own application)."""
    one = await db.get(UserJob, one_id, with_for_update=True)
    two = await db.get(UserJob, two_id, with_for_update=True)
    assert one is not None and two is not None
    if one.status == "applied" and two.status == "applied":
        return None
    keep, gone = sorted((one, two), key=lambda r: (r.status != "applied", r.first_seen_at, str(r.id)))
    gone.status, gone.duplicate_of = "duplicate", keep.id
    gone.version += 1
    if LEAD_RANK.get(gone.lead, 0) > LEAD_RANK.get(keep.lead, 0):
        keep.lead = gone.lead
    keep.apply_url = keep.apply_url or gone.apply_url
    keep.last_seen_at = max(keep.last_seen_at, gone.last_seen_at)
    keep.version += 1
    # Jobs merged into the one going now follow it.
    await db.execute(update(UserJob).where(UserJob.duplicate_of == gone.id).values(duplicate_of=keep.id))
    await db.flush()
    return keep.id


async def answer(db: AsyncSession, pair: JobDuplicate, same: bool) -> None:
    """The user's answer. Same job merges the two; different job keeps both (undoing a merge) and is remembered."""
    pair.answer, pair.answered_at = ("same" if same else "different"), datetime.now(UTC)
    if same:
        one = await db.get(UserJob, pair.user_job_id)
        two = await db.get(UserJob, pair.other_id)
        if one and two and one.status != "duplicate" and two.status != "duplicate":
            await merge(db, one.id, two.id)
    else:
        for row in await db.scalars(
            select(UserJob)
            .where(
                UserJob.status == "duplicate",
                or_(
                    (UserJob.id == pair.user_job_id) & (UserJob.duplicate_of == pair.other_id),
                    (UserJob.id == pair.other_id) & (UserJob.duplicate_of == pair.user_job_id),
                ),
            )
            .with_for_update()
        ):
            row.status, row.duplicate_of = "seen", None
            row.version += 1
    await db.flush()


def _open():
    """A pair still waiting for the user: unanswered, and neither job merged."""
    one, two = aliased(UserJob), aliased(UserJob)
    return (
        select(JobDuplicate.user_job_id, JobDuplicate.other_id)
        .join(one, one.id == JobDuplicate.user_job_id)
        .join(two, two.id == JobDuplicate.other_id)
        .where(JobDuplicate.answer.is_(None), one.status != "duplicate", two.status != "duplicate")
    )


async def possible(db: AsyncSession, user_job_ids: list[UUID]) -> set[UUID]:
    """Which of these jobs have a possible duplicate waiting for the user's answer."""
    if not user_job_ids:
        return set()
    q = _open().where(
        or_(JobDuplicate.user_job_id.in_(user_job_ids), JobDuplicate.other_id.in_(user_job_ids))
    )
    return {i for pair in (await db.execute(q)).all() for i in pair} & set(user_job_ids)


async def pairs_of(db: AsyncSession, user_job_id: UUID) -> list[tuple[JobDuplicate, UUID]]:
    """The pairs this job is in, with the other job's id; pairs the user said are different are left out."""
    rows = await db.scalars(
        select(JobDuplicate)
        .where(
            or_(JobDuplicate.user_job_id == user_job_id, JobDuplicate.other_id == user_job_id),
            or_(JobDuplicate.answer.is_(None), JobDuplicate.answer != "different"),
        )
        .order_by(JobDuplicate.created_at)
    )
    return [(p, p.other_id if p.user_job_id == user_job_id else p.user_job_id) for p in rows]
