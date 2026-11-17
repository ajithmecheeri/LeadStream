"""Warm paths and the day's suggestions, worked out from the user's connections, jobs and outreach.

Nothing here contacts anyone or opens LinkedIn: it decides who is worth a message today and drafts the note.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.candidate.models import CandidateProfile
from app.modules.catalog.models import Job
from app.modules.jobs.models import UserJob
from app.modules.matching.models import JobMatch
from app.modules.networking import notes
from app.modules.networking.companies import matches
from app.modules.networking.models import Connection, Outreach, OutreachEvent, Suggestion
from app.modules.settings.models import NotificationSettings
from app.modules.users.models import User

TOP_BANDS = ("strong", "good")
OPEN_STAGES = ("sent", "accepted", "conversation", "referral")
FOLLOW_UP_AFTER = timedelta(days=7)
NO_REPEAT_DAYS = 14
_RECRUITER = re.compile(r"recruit|talent|\bhr\b|human resources|people partner|hiring")
_LEADER = re.compile(r"\b(head|director|vp|vice president|chief|cto|ceo|founder|president|gm)\b")


def relevance(position: str | None) -> int:
    """Who is the most useful person to ask at a company: a recruiter, then a leader, then anyone."""
    p = (position or "").lower()
    return 3 if _RECRUITER.search(p) else 2 if _LEADER.search(p) else 1


@dataclass
class Target:
    """A job worth a warm path: an active Top match, or one the user applied to."""

    uj: UserJob
    job: Job
    score: int | None


async def targets(db: AsyncSession) -> list[Target]:
    rows = (
        await db.execute(
            select(UserJob, Job, JobMatch.score, JobMatch.band)
            .join(Job, Job.id == UserJob.job_id)
            .outerjoin(JobMatch, JobMatch.user_job_id == UserJob.id)
            .where(Job.company.is_not(None))
        )
    ).all()
    out = [
        Target(uj, job, score)
        for uj, job, score, band in rows
        if (uj.status in ("new", "seen") and band in TOP_BANDS) or uj.status == "applied"
    ]
    return sorted(out, key=lambda t: (-(t.score or 0), t.uj.first_seen_at))


async def people_by_company(db: AsyncSession) -> dict[str, list[Connection]]:
    out: dict[str, list[Connection]] = {}
    for c in await db.scalars(select(Connection).where(Connection.company_key.is_not(None))):
        out.setdefault(c.company_key, []).append(c)
    for people in out.values():
        people.sort(key=lambda c: (-relevance(c.position), -(c.connected_on or date.min).toordinal()))
    return out


def people_at(company: str | None, index: dict[str, list[Connection]]) -> list[Connection]:
    found = [c for key in matches(company, index) for c in index[key]]
    return sorted(found, key=lambda c: (-relevance(c.position), c.name))


async def weekly_sent(db: AsyncSession, now: datetime) -> int:
    """Invitations and messages marked sent in the last 7 days (LinkedIn limits invitations per week)."""
    return (
        await db.scalar(
            select(func.count())
            .select_from(OutreachEvent)
            .where(
                OutreachEvent.kind.in_(("sent", "followed_up")), OutreachEvent.at >= now - timedelta(days=7)
            )
        )
        or 0
    )


async def limits(db: AsyncSession, user_id: UUID) -> tuple[int, int]:
    s = await db.get(NotificationSettings, user_id)
    return (s.network_daily_cap, s.network_weekly_limit) if s else (5, 100)


async def about_me(db: AsyncSession, user_id: UUID) -> tuple[str | None, str | None, str | None]:
    """The user's first name, headline and own invitation note."""
    first = await db.scalar(select(User.first_name).where(User.id == user_id))
    cand = await db.get(CandidateProfile, user_id)
    return first, cand.headline if cand else None, cand.invite_note if cand else None


async def set_invite_note(db: AsyncSession, user_id: UUID, note: str | None) -> None:
    """Save the user's invitation note and rewrite it into today's open "find someone" suggestions."""
    cand = await db.get(CandidateProfile, user_id, with_for_update=True)
    if cand is None:
        return
    cand.invite_note = note.strip() if note and note.strip() else None
    me, headline, own = await about_me(db, user_id)
    for s in await db.scalars(
        select(Suggestion).where(Suggestion.kind == "target", Suggestion.status == "open")
    ):
        p = s.payload or {}
        note_now = notes.target(p.get("company", ""), p.get("job_title", ""), headline, me, own)
        s.payload = {**p, "note": note_now}


async def build_day(db: AsyncSession, user_id: UUID, day: date, regenerate: bool = False) -> list[Suggestion]:
    """The day's suggestions, made the first time they're asked for. `regenerate` replaces the open ones."""
    existing = list(
        await db.scalars(select(Suggestion).where(Suggestion.day == day).order_by(Suggestion.position))
    )
    if existing and not regenerate:
        return existing
    if regenerate:
        await db.execute(delete(Suggestion).where(Suggestion.day == day, Suggestion.status == "open"))
        existing = [s for s in existing if s.status != "open"]

    now = datetime.now(UTC)
    cap, weekly_limit = await limits(db, user_id)
    room = max(0, cap - len(existing))
    me, headline, own = await about_me(db, user_id)
    since = day - timedelta(days=NO_REPEAT_DAYS)
    recent = set(await db.scalars(select(Suggestion.person_key).where(Suggestion.day >= since)))
    open_outreach = list(await db.scalars(select(Outreach).where(Outreach.stage.in_(OPEN_STAGES))))
    busy = {o.connection_id for o in open_outreach if o.connection_id} | {
        (o.profile_url or "").lower() for o in open_outreach if o.profile_url
    }
    picked: list[Suggestion] = []

    def add(s: Suggestion) -> None:
        s.position = len(existing) + len(picked)
        picked.append(s)
        recent.add(s.person_key)

    # Follow-ups first: someone already waiting on the user.
    titles = dict(
        (
            await db.execute(
                select(UserJob.id, Job.title)
                .join(Job, Job.id == UserJob.job_id)
                .where(UserJob.id.in_([o.user_job_id for o in open_outreach if o.user_job_id]))
            )
        ).all()
    )
    for o in sorted(open_outreach, key=lambda o: o.stage_at):
        if len(picked) >= room:
            break
        last = max(o.stage_at, o.followed_up_at or o.stage_at)
        key = f"outreach:{o.id}"
        if o.stage != "sent" or now - last < FOLLOW_UP_AFTER or key in recent:
            continue
        first = (o.person_name or "").split(" ")[0] or None
        job_title = titles.get(o.user_job_id) if o.user_job_id else None
        add(
            Suggestion(
                user_id=user_id,
                day=day,
                kind="followup",
                person_key=key,
                outreach_id=o.id,
                user_job_id=o.user_job_id,
                payload={
                    "name": o.person_name,
                    "title": o.title,
                    "company": o.company,
                    "profile_url": o.profile_url,
                    "job_title": job_title,
                    "why": f"You wrote {(now - o.stage_at).days} days ago and haven't heard back",
                    "note": notes.followup(first, o.company, job_title, me),
                },
            )
        )

    if await weekly_sent(db, now) < weekly_limit:
        index = await people_by_company(db)
        jobs = await targets(db)
        companies_done: set[str] = set()
        # Warm: one person per company, best match first.
        for t in jobs:
            if len(picked) >= room:
                break
            company = t.job.company or ""
            if company.lower() in companies_done:
                continue
            person = next(
                (
                    c
                    for c in people_at(company, index)
                    if c.person_key not in recent
                    and c.id not in busy
                    and (c.profile_url or "").lower() not in busy
                ),
                None,
            )
            if person is None:
                continue
            companies_done.add(company.lower())
            score = f", which matches you at {t.score}%" if t.score is not None else ""
            add(
                Suggestion(
                    user_id=user_id,
                    day=day,
                    kind="warm",
                    person_key=person.person_key,
                    connection_id=person.id,
                    user_job_id=t.uj.id,
                    payload={
                        "name": person.name,
                        "title": person.position,
                        "company": person.company or company,
                        "profile_url": person.profile_url,
                        "job_title": t.job.title,
                        "job_score": t.score,
                        "why": f"1st-degree connection at {person.company or company}, hiring a {t.job.title}{score}",
                        "note": notes.warm(
                            person.first_name, person.company or company, t.job.title, headline, me
                        ),
                    },
                )
            )
        # Target: Top matches where the user knows no one; who to look for, and a search link.
        for t in jobs:
            if len(picked) >= room:
                break
            company = (t.job.company or "").removesuffix("...").removesuffix("…").strip()
            if not company or company.lower() in companies_done or people_at(t.job.company, index):
                continue
            if t.uj.status == "applied":
                continue  # a cold invitation after applying is rarely worth it; warm paths still are
            role = notes.target_role(t.job.title)
            key = f"target:{company.lower()}:{role.lower()}"
            if key in recent:
                continue
            companies_done.add(company.lower())
            add(
                Suggestion(
                    user_id=user_id,
                    day=day,
                    kind="target",
                    person_key=key,
                    user_job_id=t.uj.id,
                    payload={
                        "role": role,
                        "company": company,
                        "job_title": t.job.title,
                        "job_score": t.score,
                        "search_url": notes.people_search_url(f"{role} {company}"),
                        "why": f"You don't know anyone at {company} yet, and it's hiring a {t.job.title}",
                        "note": notes.target(company, t.job.title, headline, me, own),
                    },
                )
            )
    for s in picked:
        db.add(s)
    await db.flush()
    return existing + picked
