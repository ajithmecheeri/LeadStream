"""The answer bank, and each job's readiness with the blockers the user can clear from the job page."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import User, UserDB
from app.core.errors import AppError, Conflict, NotFound
from app.modules.catalog.models import Job
from app.modules.jobs.models import UserJob
from app.modules.matching.models import JobMatch
from app.modules.readiness.models import Answer
from app.modules.readiness.questions import BY_KEY, MAX_CUSTOM, STANDARD, slug
from app.modules.readiness.schemas import (
    AnswerIn,
    AnswerList,
    AnswerOut,
    BlockerOut,
    CustomAnswerIn,
    ReadinessOut,
    ResolveIn,
)
from app.modules.readiness.service import Readiness, evaluate, load_context

router = APIRouter(tags=["readiness"])
STALE_AFTER = timedelta(days=30)


def _readiness_out(r: Readiness | None) -> ReadinessOut:
    if r is None:
        raise AppError(422, "not_a_top_match", "Readiness is worked out for Top matches only")
    return ReadinessOut(status=r.status, blockers=[BlockerOut(**b.__dict__) for b in r.blockers])


async def _job(
    db: AsyncSession, user_job_id: UUID, lock: bool = False
) -> tuple[UserJob, Job, JobMatch | None]:
    uj = await db.get(UserJob, user_job_id, with_for_update=lock)
    if uj is None:
        raise NotFound("Job")
    job = await db.get(Job, uj.job_id)
    assert job is not None
    return uj, job, await db.get(JobMatch, uj.id)


async def _shared_answers(db: AsyncSession) -> dict[str, Answer]:
    return {a.key: a for a in await db.scalars(select(Answer).where(Answer.search_profile_id.is_(None)))}


async def _save(
    db: AsyncSession, user_id: UUID, key: str, question: str, answer: str, version: int | None
) -> Answer:
    row = (await _shared_answers(db)).get(key)
    if row is None:
        row = Answer(user_id=user_id, key=key, question=question, answer=answer)
        db.add(row)
    else:
        if version is not None and version != row.version:
            raise Conflict("version_conflict", "This answer was changed elsewhere. Reload and try again.")
        row.answer, row.question = answer, question
        row.version += 1
    await db.flush()
    await db.refresh(row)
    return row


# --- Answer bank --------------------------------------------------------------------------------------------


@router.get("/answers", response_model=AnswerList)
async def list_answers(user: User, db: UserDB):
    """The common screening questions (answered from the bank, else from your profile) and your own ones."""
    ctx = await load_context(db, user.id)
    now = datetime.now(UTC)

    def out(key: str, question: str, row: Answer | None, standard: bool, required: bool, profile: str | None):
        return AnswerOut(
            key=key,
            question=question,
            answer=row.answer if row else profile,
            source="you" if row else ("profile" if profile else None),
            standard=standard,
            required=required,
            updated_at=row.updated_at if row else None,
            stale=bool(row and now - row.updated_at > STALE_AFTER),
            version=row.version if row else None,
            choices=list(BY_KEY[key].choices) if key in BY_KEY else [],
        )

    items = [
        out(
            s.key,
            s.question,
            ctx.answers.get(s.key),
            True,
            s.required,
            s.from_profile(ctx.candidate) if ctx.candidate else None,
        )
        for s in STANDARD
    ]
    custom = sorted((a for k, a in ctx.answers.items() if k not in BY_KEY), key=lambda a: a.created_at)
    items += [out(a.key, a.question, a, False, False, None) for a in custom]
    return AnswerList(items=items)


@router.post("/answers", response_model=AnswerOut, status_code=status.HTTP_201_CREATED)
async def add_answer(body: CustomAnswerIn, user: User, db: UserDB):
    """Add your own question and answer, e.g. "Do you have a valid passport?"."""
    key = slug(body.question)
    existing = await _shared_answers(db)
    if key in BY_KEY or key in existing:
        raise Conflict("duplicate", "You already have this question in your answer bank")
    if sum(1 for k in existing if k not in BY_KEY) >= MAX_CUSTOM:
        raise AppError(422, "limit_reached", f"You can keep up to {MAX_CUSTOM} questions of your own")
    row = await _save(db, user.id, key, body.question, body.answer, None)
    return AnswerOut(
        key=row.key,
        question=row.question,
        answer=row.answer,
        source="you",
        standard=False,
        required=False,
        updated_at=row.updated_at,
        stale=False,
        version=row.version,
    )


@router.put("/answers/{key}", response_model=AnswerOut)
async def save_answer(key: str, body: AnswerIn, user: User, db: UserDB):
    """Answer a common question, or change your answer to any question."""
    existing = (await _shared_answers(db)).get(key)
    if key not in BY_KEY and existing is None:
        raise NotFound("Question")
    question = BY_KEY[key].question if key in BY_KEY else existing.question  # type: ignore[union-attr]
    row = await _save(db, user.id, key, question, body.answer, body.version)
    std = BY_KEY.get(key)
    return AnswerOut(
        key=row.key,
        question=row.question,
        answer=row.answer,
        source="you",
        standard=std is not None,
        required=bool(std and std.required),
        updated_at=row.updated_at,
        stale=False,
        version=row.version,
    )


@router.delete("/answers/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_answer(key: str, _: User, db: UserDB):
    """Delete your own question, or clear a saved answer to a common one (your profile's answer applies again)."""
    row = (await _shared_answers(db)).get(key)
    if row is None:
        raise NotFound("Answer")
    await db.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Readiness ----------------------------------------------------------------------------------------------


@router.get("/jobs/{user_job_id}/readiness", response_model=ReadinessOut)
async def get_readiness(user_job_id: UUID, user: User, db: UserDB):
    uj, job, match = await _job(db, user_job_id)
    return _readiness_out(evaluate(await load_context(db, user.id), uj, job, match))


@router.post("/jobs/{user_job_id}/blockers/{key}/resolve", response_model=ReadinessOut)
async def resolve_blocker(user_job_id: UUID, key: str, body: ResolveIn, user: User, db: UserDB):
    """Clear a blocker: answer a question (saved to the answer bank for every job) or accept a gap."""
    uj, job, match = await _job(db, user_job_id, lock=True)
    ctx = await load_context(db, user.id)
    current = evaluate(ctx, uj, job, match)
    blocker = next((b for b in (current.blockers if current else []) if b.key == key), None)
    if blocker is None:
        raise NotFound("Blocker")
    if blocker.kind == "question":
        if not body.answer:
            raise AppError(
                422,
                "validation_error",
                "Write an answer",
                [{"field": "answer", "message": "Write an answer"}],
            )
        q_key = key.split(":", 1)[1]
        await _save(db, user.id, q_key, blocker.question or blocker.title, body.answer, None)
    elif blocker.kind == "gap":
        uj.acknowledged = [*(uj.acknowledged or []), key]
        await db.flush()
    else:
        what = (
            "Paste the description on the job page"
            if blocker.kind == "description"
            else "Add a cover letter on your Profile"
        )
        raise AppError(422, "resolve_elsewhere", f"{what}; this clears on its own.")
    return _readiness_out(evaluate(await load_context(db, user.id), uj, job, match))
