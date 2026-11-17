"""Skill Match profiles made from resumes (user feedback 2026-11-13).

Every resume has one match profile. A new resume gets one with the settings of the user's first profile (or the
defaults), its target roles from the resume's headline and its skills from the resume's skills section. When the
resume changes, its skills are read again; the skills the user added stay as they are.
"""

import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.candidate.models import CandidateProfile
from app.modules.documents.models import Resume
from app.modules.documents.reader import read
from app.modules.matching import skills as sk
from app.modules.matching import taxonomy
from app.modules.profiles.models import SearchProfile
from app.modules.profiles.schemas import DEFAULT_WEIGHTS, MAX_SKILLS, SKILL_MAX_CHARS

ALL_WORK_MODELS = ["Hybrid", "On-site", "Remote"]
MAX_RESUME_SKILLS = 120
_ROLE_SPLIT = re.compile(r"\s*[|•·;]\s*")


def target_roles(headline: str | None, title: str | None) -> list[str]:
    """ "VP, Product Development | Enterprise Technology Leader" → both parts, without the comma after a grade
    ("VP Product Development"), so a job title naming the same words matches."""
    out: list[str] = []
    for part in [*_ROLE_SPLIT.split(headline or ""), title or ""]:
        role = " ".join(re.sub(r"(?<=\w),(?=\s)", "", part).split())[:60]
        if role and len(role.split()) <= 8 and role.lower() not in {r.lower() for r in out}:
            out.append(role)
    return out[:5]


def resume_skills(text: str) -> list[str]:
    """The skills a resume lists (its skills section), or, without one, the known skills its text names."""
    found = read(text).skills or [s for s in sk.VOCABULARY if sk.match(text.lower(), s) == 1.0]
    out: list[str] = []
    for s in found:
        s = " ".join(s.split())
        if s and len(s) <= SKILL_MAX_CHARS and s.lower() not in {o.lower() for o in out}:
            out.append(s)
    return out[:MAX_RESUME_SKILLS]


def refresh_from_resume(profile: SearchProfile, resume: Resume) -> None:
    """Read the resume's skills again (and its roles, while the profile has none)."""
    profile.resume_skills = resume_skills(resume.text)
    if not profile.target_roles:
        facts = read(resume.text)
        profile.target_roles = target_roles(facts.headline, facts.current_title)
    profile.resume_read_at = datetime.now(UTC)


def needs_refresh(profile: SearchProfile, resume: Resume) -> bool:
    return profile.resume_read_at is None or (resume.updated_at or resume.created_at) > profile.resume_read_at


def not_in_resume(profile: SearchProfile, resume: Resume | None) -> list[str]:
    """Skills the user added that the resume doesn't show yet: worth adding to the resume itself."""
    if resume is None:
        return []
    listed = {s.lower() for s in profile.resume_skills}
    text = resume.text.lower()
    return [s for s in profile.skills if not sk.shows(text, listed, s)]


async def _unique_name(db: AsyncSession, label: str) -> str:
    base, n = " ".join(label.split())[:50] or "Resume", 1
    name = base
    while await db.scalar(select(SearchProfile.id).where(func.lower(SearchProfile.name) == name.lower())):
        n += 1
        name = f"{base} ({n})"
    return name


async def new_profile(db: AsyncSession, user_id: UUID, resume: Resume) -> SearchProfile:
    """A match profile for a resume: the first profile's settings (or the defaults), the resume's roles and skills."""
    template = await db.scalar(select(SearchProfile).order_by(SearchProfile.created_at).limit(1))
    cand = await db.get(CandidateProfile, user_id)
    facts = read(resume.text)
    level = taxonomy.seniority(facts.current_title or facts.headline)
    location = (
        (cand.current_location if cand else None) or (facts.location or "").split(",")[0].strip() or None
    )
    profile = SearchProfile(
        user_id=user_id,
        resume_id=resume.id,
        name=await _unique_name(db, resume.label),
        target_roles=[],
        # The first profile's places; else where the user said at sign-up they want to work; else where they live.
        locations=list(template.locations)
        if template
        else (list(cand.job_locations) if cand and cand.job_locations else ([location] if location else [])),
        work_models=list(template.work_models) if template else list(ALL_WORK_MODELS),
        min_seniority=template.min_seniority if template else max(1, min(9, (level or 6) - 1)),
        excluded_companies=list(template.excluded_companies) if template else [],
        weights=dict(template.weights) if template else dict(DEFAULT_WEIGHTS),
        threshold=template.threshold if template else 85,
        active=True,
        skills=[],
        version=1,
    )
    refresh_from_resume(profile, resume)
    db.add(profile)
    await db.flush()
    return profile


async def ensure_match_profiles(db: AsyncSession, user_id: UUID) -> bool:
    """Give every resume its match profile and re-read the skills of resumes changed since. True if anything
    changed (the caller rescores)."""
    resumes = list(await db.scalars(select(Resume).order_by(Resume.is_primary.desc(), Resume.created_at)))
    if not resumes:
        return False
    linked = {
        p.resume_id: p
        for p in await db.scalars(select(SearchProfile).where(SearchProfile.resume_id.is_not(None)))
    }
    changed = False
    for r in resumes:
        p = linked.get(r.id)
        if p is None:
            await new_profile(db, user_id, r)
            changed = True
        elif needs_refresh(p, r):
            refresh_from_resume(p, r)
            p.version += 1
            changed = True
    if changed:
        await db.flush()
    return changed


async def add_skill_to(db: AsyncSession, row: SearchProfile, skill: str) -> bool:
    """Append a skill the user added; False if the profile already has it (added or from the resume)."""
    skill = " ".join(skill.split())
    if len(skill) > SKILL_MAX_CHARS:
        raise AppError(422, "validation_error", f"A skill can be at most {SKILL_MAX_CHARS} characters")
    if skill.lower() in {s.lower() for s in [*row.skills, *row.resume_skills]}:
        return False
    if len(row.skills) >= MAX_SKILLS:
        raise AppError(422, "limit_reached", f"A profile can have up to {MAX_SKILLS} skills you added")
    row.skills = [*row.skills, skill]
    row.version += 1
    await db.flush()
    await db.refresh(row)
    return True
