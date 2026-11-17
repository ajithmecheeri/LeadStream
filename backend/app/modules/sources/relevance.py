"""Which feed and job-board listings reach a user (decision 3 in docs/plan-m9.md).

A company feed lists every opening, most of them for other people. Alert emails aren't checked: the user chose
those alerts. Unknown facts never rule a job out, except a title with no seniority word for a senior user.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.candidate.models import CandidateProfile
from app.modules.catalog.parsers import JobCard
from app.modules.documents.models import Resume
from app.modules.documents.reader import read
from app.modules.matching import scoring, taxonomy
from app.modules.profiles.models import SearchProfile
from app.modules.profiles.schemas import SENIORITY


@dataclass(frozen=True)
class Audience:
    floor: int  # lowest seniority level (1-9) the user wants
    families: frozenset[str]  # the user's job families; empty when unknown
    profiles: tuple[scoring.ProfileInput, ...]  # active search profiles, for their hard filters
    queries: tuple[tuple[str, str], ...]  # (role, location) pairs for job-search APIs


def floor_from_years(years: int | None) -> int:
    if years is None:
        return 1
    return 4 if years >= 18 else 3 if years >= 12 else 2 if years >= 6 else 1


async def audience(db: AsyncSession, user_id) -> Audience:
    """What the relevance check needs to know about the user (run inside their user_scope)."""
    cand = await db.get(CandidateProfile, user_id)
    profiles = list(await db.scalars(select(SearchProfile).where(SearchProfile.active)))
    resume = await db.scalar(select(Resume).order_by(Resume.is_primary.desc(), Resume.created_at).limit(1))
    facts = read(resume.text) if resume else None
    years = (
        cand.years_experience
        if cand and cand.years_experience is not None
        else (facts.years_experience if facts else None)
    )
    floor = min((p.min_seniority for p in profiles), default=floor_from_years(years))
    fam_text = " ".join(
        [
            (cand.headline or "") if cand else "",
            (facts.current_title or "") if facts else "",
            (facts.headline or "") if facts else "",
        ]
        + [r for p in profiles for r in p.target_roles]
    )
    queries = [(role, loc) for p in profiles for role in p.target_roles for loc in (p.locations or [""])]
    return Audience(
        floor=floor,
        families=frozenset(taxonomy.families(fam_text)),
        profiles=tuple(_profile(p) for p in profiles),
        queries=tuple(dict.fromkeys(queries)),
    )


def _profile(p: SearchProfile) -> scoring.ProfileInput:
    return scoring.ProfileInput(
        id=str(p.id),
        name=p.name,
        target_roles=p.target_roles,
        locations=p.locations,
        work_models=p.work_models,
        min_seniority=p.min_seniority,
        excluded_companies=p.excluded_companies,
        weights=p.weights,
        threshold=p.threshold,
    )


# Plainer words than the profile's level names for the lowest levels ("Engineer" reads wrong for an analyst).
_LEVEL_WORDS = {1: "individual contributor", 2: "team lead"}


def relevant(card: JobCard, who: Audience) -> bool:
    return why_not(card, who) is None


def why_not(card: JobCard, who: Audience) -> str | None:
    """Why a listing doesn't reach the user (shown on Job sources → Last run), or None when it does."""
    level = taxonomy.seniority(card.title)
    if level is None:
        if who.floor > 2:
            return "The title doesn't say its level"
    elif level < who.floor - 1:
        return f"Below your level ({_LEVEL_WORDS.get(level) or SENIORITY.get(level, level)} role)"
    job_families = taxonomy.title_families(card.title)
    if who.families and job_families and not (job_families & who.families):
        names = ", ".join(sorted(f.replace("_", " ") for f in job_families))
        return f"Another field ({names})"
    if who.profiles:
        job = scoring.JobInput(
            title=card.title,
            company=card.company,
            location=card.location,
            work_model=card.work_model,
            experience=card.experience,
            salary=card.salary,
            skills=list(card.skills),
            text="",
            full_description=False,
        )
        reasons = [scoring.hard_filter(job, p) for p in who.profiles]
        return None if any(r is None for r in reasons) else reasons[0]
    return None
