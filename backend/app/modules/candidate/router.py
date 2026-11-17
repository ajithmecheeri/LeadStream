"""The candidate profile: facts shared by every search profile (skills, domains, notice, CTC)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import User, UserDB
from app.core.errors import Conflict, NotFound
from app.modules.candidate.locations import MAX_JOB_LOCATIONS, check_locations
from app.modules.candidate.models import CandidateProfile
from app.modules.documents.models import Resume
from app.modules.documents.reader import ResumeFacts, read
from app.modules.llm.gateway import run
from app.modules.matching.service import queue_scoring
from app.modules.profiles.models import SearchProfile

router = APIRouter(tags=["candidate"])


def _norm_list(values: list[str]) -> list[str]:
    seen, out = set(), []
    for v in values:
        k = " ".join(v.strip().lower().split())
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


class CandidateIn(BaseModel):
    headline: str | None = Field(None, max_length=200)
    summary: str | None = Field(None, max_length=4000)
    current_location: str | None = Field(None, max_length=120)
    years_experience: int | None = Field(None, ge=0, le=60)
    skills: list[str] = Field(default_factory=list, max_length=200)
    domains: list[str] = Field(default_factory=list, max_length=50)
    notice_days: int | None = Field(None, ge=0, le=365)
    current_ctc: str | None = Field(None, max_length=60)
    expected_ctc: str | None = Field(None, max_length=60)
    work_authorization: str | None = Field(None, max_length=200)
    linkedin_url: str | None = Field(None, max_length=300, pattern=r"^https://([a-z]+\.)?linkedin\.com/.*$")
    job_locations: list[str] | None = Field(
        None, max_length=MAX_JOB_LOCATIONS, description="Where you want to work; left as it is when not sent"
    )
    version: int = Field(description="The version you last read; a stale version returns 409")

    _skills = field_validator("skills", "domains")(lambda cls, v: _norm_list(v))

    _places = field_validator("job_locations")(lambda cls, v: None if v is None else check_locations(v))


class JobLocationsIn(BaseModel):
    job_locations: list[str] = Field(min_length=1, max_length=MAX_JOB_LOCATIONS)
    _places = field_validator("job_locations")(lambda cls, v: check_locations(v))


class CandidateOut(BaseModel):
    model_config = {"from_attributes": True}
    headline: str | None
    summary: str | None
    current_location: str | None
    years_experience: int | None
    skills: list[str]
    domains: list[str]
    notice_days: int | None
    current_ctc: str | None
    expected_ctc: str | None
    work_authorization: str | None
    linkedin_url: str | None
    job_locations: list[str]
    version: int
    updated_at: datetime
    completeness: int = Field(description="0-100: how much of the profile the matcher can use")


def _out(row: CandidateProfile, has_resume: bool) -> CandidateOut:
    checks = [
        has_resume,  # its match profile holds the skills (2026-11-13)
        row.summary,
        row.years_experience is not None,
        row.domains,
        row.notice_days is not None,
        row.expected_ctc,
        row.current_location,
    ]
    pct = round(100 * sum(1 for c in checks if c) / len(checks))
    return CandidateOut.model_validate(
        {
            **{c: getattr(row, c) for c in CandidateOut.model_fields if c != "completeness"},
            "completeness": pct,
        }
    )


@router.get("/candidate", response_model=CandidateOut)
async def get_candidate(user: User, db: UserDB):
    row = await db.get(CandidateProfile, user.id)
    if row is None:
        raise NotFound("Candidate profile")
    return _out(row, await _has_resume(db))


async def _has_resume(db: AsyncSession) -> bool:
    return await db.scalar(select(Resume.id).limit(1)) is not None


class FromResumeIn(BaseModel):
    resume_id: UUID


class CandidateDraft(ResumeFacts):
    """Facts read from a resume, for the user to review. Nothing is saved until they PUT /candidate."""

    method: Literal["rules", "llm"]


@router.post("/candidate/from-resume", response_model=CandidateDraft)
async def candidate_from_resume(body: FromResumeIn, user: User, db: UserDB):
    """Read a resume from the library into candidate-profile fields (Claude when configured, else rules)."""
    resume = await db.get(Resume, body.resume_id)
    if resume is None:
        raise NotFound("Resume")
    facts = await run(db, user.id, "resume_extract", ResumeFacts, {"resume": resume.text}, max_tokens=2000)
    if facts is not None:
        return CandidateDraft(**facts.model_dump(), method="llm")
    return CandidateDraft(**read(resume.text).model_dump(), method="rules")


@router.put("/candidate", response_model=CandidateOut)
async def put_candidate(body: CandidateIn, user: User, db: UserDB):
    row = await db.get(CandidateProfile, user.id, with_for_update=True)
    if row is None:
        raise NotFound("Candidate profile")
    if body.version != row.version:
        raise Conflict("version_conflict", "This profile was changed elsewhere. Reload and try again.")
    for k, v in body.model_dump(exclude={"version"}).items():
        if k == "job_locations" and v is None:
            continue
        setattr(row, k, v)
    row.version += 1
    await db.flush()
    await db.refresh(row)
    await queue_scoring(user.id, "candidate profile changed")
    return _out(row, await _has_resume(db))


@router.put("/candidate/job-locations", response_model=CandidateOut)
async def put_job_locations(body: JobLocationsIn, user: User, db: UserDB):
    """Where you want to work (asked once of accounts made before sign-up asked it). Match profiles without
    any location take these too."""
    row = await db.get(CandidateProfile, user.id, with_for_update=True)
    if row is None:
        raise NotFound("Candidate profile")
    row.job_locations = body.job_locations
    row.version += 1
    filled = 0
    for p in await db.scalars(select(SearchProfile).where(SearchProfile.locations == [])):
        p.locations, p.version = list(body.job_locations), p.version + 1
        filled += 1
    await db.flush()
    await db.refresh(row)
    if filled:
        await queue_scoring(user.id, "job locations set")
    return _out(row, await _has_resume(db))
