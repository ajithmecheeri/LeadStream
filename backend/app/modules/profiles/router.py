"""Skill Match profiles (search profiles): one per resume, made from it, each with its own roles, weights,
threshold and skills (user feedback 2026-11-13)."""

from uuid import UUID

from fastapi import APIRouter, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import User, UserDB
from app.core.errors import AppError, Conflict, NotFound
from app.modules.documents.models import Resume
from app.modules.matching.service import queue_scoring
from app.modules.profiles import service
from app.modules.profiles.models import SearchProfile
from app.modules.profiles.schemas import (
    DEFAULT_WEIGHTS,
    FACTORS,
    MAX_PROFILES,
    SENIORITY,
    ProfilesMeta,
    SearchProfileIn,
    SearchProfileOut,
    SearchProfilePatch,
    SkillIn,
)

router = APIRouter(tags=["profiles"])


async def _name_taken(db: AsyncSession, name: str, exclude: UUID | None = None) -> bool:
    q = select(SearchProfile.id).where(func.lower(SearchProfile.name) == name.lower())
    if exclude:
        q = q.where(SearchProfile.id != exclude)
    return (await db.scalar(q)) is not None


async def _get(db: AsyncSession, profile_id: UUID, lock: bool = False) -> SearchProfile:
    # RLS already limits rows to the current user; another user's id simply isn't found.
    row = await db.get(SearchProfile, profile_id, with_for_update=lock)
    if row is None:
        raise NotFound("Search profile")
    return row


async def _out(db: AsyncSession, row: SearchProfile) -> SearchProfileOut:
    resume = await db.get(Resume, row.resume_id) if row.resume_id else None
    return SearchProfileOut.model_validate(row).model_copy(
        update={
            "resume_label": resume.label if resume else None,
            "not_in_resume": service.not_in_resume(row, resume),
        }
    )


async def _ensure(db: AsyncSession, user_id: UUID) -> None:
    if await service.ensure_match_profiles(db, user_id):
        await queue_scoring(user_id, "match profiles made from resumes")


@router.get("/profiles/meta", response_model=ProfilesMeta)
async def profiles_meta(_: User):
    return ProfilesMeta(
        factors=FACTORS,
        default_weights=DEFAULT_WEIGHTS,
        seniority=SENIORITY,
        work_models=["Remote", "Hybrid", "On-site"],
        max_profiles=MAX_PROFILES,
    )


@router.get("/profiles", response_model=list[SearchProfileOut])
async def list_profiles(user: User, db: UserDB):
    """Your match profiles, one per resume (the primary resume's first)."""
    await _ensure(db, user.id)
    rows = list(
        await db.execute(
            select(SearchProfile)
            .outerjoin(Resume, Resume.id == SearchProfile.resume_id)
            .order_by(Resume.is_primary.desc().nulls_last(), Resume.created_at, SearchProfile.created_at)
        )
    )
    return [await _out(db, r[0]) for r in rows]


@router.post("/profiles", response_model=SearchProfileOut, status_code=status.HTTP_201_CREATED)
async def create_profile(body: SearchProfileIn, user: User, db: UserDB):
    count = await db.scalar(select(func.count()).select_from(SearchProfile))
    if (count or 0) >= MAX_PROFILES:
        raise AppError(422, "limit_reached", f"You can have up to {MAX_PROFILES} search profiles")
    if await _name_taken(db, body.name):
        raise Conflict("name_taken", "You already have a search profile with this name")
    row = SearchProfile(user_id=user.id, **body.model_dump())
    db.add(row)
    await db.flush()
    await db.refresh(row)
    await queue_scoring(user.id, "search profile added")
    return await _out(db, row)


@router.get("/profiles/{profile_id}", response_model=SearchProfileOut)
async def get_profile(profile_id: UUID, user: User, db: UserDB):
    await _ensure(db, user.id)
    return await _out(db, await _get(db, profile_id))


@router.patch("/profiles/{profile_id}", response_model=SearchProfileOut)
async def patch_profile(profile_id: UUID, body: SearchProfilePatch, user: User, db: UserDB):
    row = await _get(db, profile_id, lock=True)
    if body.version != row.version:
        raise Conflict("version_conflict", "This profile was changed elsewhere. Reload and try again.")
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    if "name" in changes and await _name_taken(db, changes["name"], exclude=row.id):
        raise Conflict("name_taken", "You already have a search profile with this name")
    for k, v in changes.items():
        setattr(row, k, v)
    row.version += 1
    await db.flush()
    await db.refresh(row)
    await queue_scoring(user.id, "search profile changed")
    return await _out(db, row)


@router.post("/profiles/{profile_id}/refresh", response_model=SearchProfileOut)
async def refresh_profile(profile_id: UUID, user: User, db: UserDB):
    """Read the resume's skills again (after you add a skill to the resume, say). Skills you added stay."""
    row = await _get(db, profile_id, lock=True)
    resume = await db.get(Resume, row.resume_id) if row.resume_id else None
    if resume is None:
        raise AppError(422, "no_resume", "This profile isn't made from a resume")
    service.refresh_from_resume(row, resume)
    row.version += 1
    await db.flush()
    await db.refresh(row)
    await queue_scoring(user.id, "match profile refreshed")
    return await _out(db, row)


@router.post("/profiles/{profile_id}/skills", response_model=SearchProfileOut)
async def add_skill(profile_id: UUID, body: SkillIn, user: User, db: UserDB):
    """Add a skill you have to this profile (a job asked for it and the resume doesn't show it)."""
    row = await _get(db, profile_id, lock=True)
    await service.add_skill_to(db, row, body.skill)
    await queue_scoring(user.id, "skill added")
    return await _out(db, row)


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(profile_id: UUID, user: User, db: UserDB):
    row = await _get(db, profile_id)
    if row.resume_id:
        raise Conflict(
            "made_from_resume", "This profile belongs to a resume. Delete the resume to remove it."
        )
    await db.delete(row)
    await queue_scoring(user.id, "search profile deleted")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
