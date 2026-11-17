"""The apply profile (milestone 14.1) and a job's Apply kit (14.2)."""

from uuid import UUID

from fastapi import APIRouter

from app.core.deps import User, UserDB
from app.core.errors import Conflict, NotFound
from app.modules.apply import service
from app.modules.apply.models import ApplyProfile
from app.modules.apply.schemas import ApplyDraft, ApplyKitOut, ApplyProfileIn, ApplyProfileOut, FromResumeIn
from app.modules.documents.models import Resume
from app.modules.jobs.models import UserJob

router = APIRouter(tags=["apply"])


def _out(row: ApplyProfile | None) -> ApplyProfileOut:
    if row is None:
        return ApplyProfileOut(version=0, updated_at=None)
    return ApplyProfileOut(
        phone=row.phone,
        address_line1=row.address_line1,
        address_line2=row.address_line2,
        city=row.city,
        state=row.state,
        postal_code=row.postal_code,
        country=row.country,
        websites=list(row.websites or []),
        languages=row.languages or [],
        work_history=row.work_history or [],
        education=row.education or [],
        version=row.version,
        updated_at=row.updated_at,
    )


@router.get("/apply-profile", response_model=ApplyProfileOut)
async def get_apply_profile(user: User, db: UserDB):
    """What application forms ask for beyond your profile: phone, address, work history, education, languages."""
    return _out(await db.get(ApplyProfile, user.id))


@router.put("/apply-profile", response_model=ApplyProfileOut)
async def put_apply_profile(body: ApplyProfileIn, user: User, db: UserDB):
    """Save the whole apply profile. Send the version you read (0 the first time); a stale one gets 409."""
    row = await db.get(ApplyProfile, user.id, with_for_update=True)
    if body.version != (row.version if row else 0):
        raise Conflict("version_conflict", "Your apply profile was changed elsewhere. Reload and try again.")
    values = body.model_dump(mode="json", exclude={"version"})
    if row is None:
        row = ApplyProfile(user_id=user.id, **values, version=1)
        db.add(row)
    else:
        for k, v in values.items():
            setattr(row, k, v)
        row.version += 1
    await db.flush()
    await db.refresh(row)
    return _out(row)


@router.post("/apply-profile/from-resume", response_model=ApplyDraft)
async def apply_profile_from_resume(body: FromResumeIn, user: User, db: UserDB):
    """Read phone, city, work history and education from a resume, for you to review. Nothing is saved."""
    resume = await db.get(Resume, body.resume_id)
    if resume is None:
        raise NotFound("Resume")
    return service.draft(resume.text)


@router.get("/jobs/{user_job_id}/apply-kit", response_model=ApplyKitOut)
async def apply_kit(user_job_id: UUID, user: User, db: UserDB):
    """Everything this job's application form is likely to ask, in Workday's order, to copy field by field, with
    the suggested resume and cover letter."""
    if await db.get(UserJob, user_job_id) is None:
        raise NotFound("Job")
    sections, missing = service.sections(await service.load(db, user.id))
    return ApplyKitOut(sections=sections, documents=await service.documents(db, user_job_id), missing=missing)
