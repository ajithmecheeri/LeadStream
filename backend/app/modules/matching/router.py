"""Matching status and a manual re-score."""

from datetime import datetime

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.core.deps import User, UserDB
from app.modules.documents.models import CoverLetter, Resume
from app.modules.jobs.models import UserJob
from app.modules.llm.gateway import embedder
from app.modules.matching.models import JobMatch
from app.modules.matching.service import SCORE, queue_scoring

router = APIRouter(tags=["matching"])


class MatchingStatus(BaseModel):
    resumes: int
    cover_letters: int
    scored: int
    unscored: int  # active jobs without a score
    last_scored_at: datetime | None
    scoring: bool  # a scoring run is queued or running
    similarity: bool  # text similarity (Voyage) is configured
    ai: bool  # Claude is configured; otherwise rules only


class Queued(BaseModel):
    queued: bool


@router.get("/matching/status", response_model=MatchingStatus)
async def matching_status(user: User, db: UserDB):
    resumes = await db.scalar(select(func.count()).select_from(Resume)) or 0
    letters = await db.scalar(select(func.count()).select_from(CoverLetter)) or 0
    scored, last = (await db.execute(select(func.count(), func.max(JobMatch.scored_at)))).one()
    unscored = await db.scalar(
        select(func.count())
        .select_from(UserJob)
        .outerjoin(JobMatch, JobMatch.user_job_id == UserJob.id)
        .where(UserJob.status != "ignored", JobMatch.user_job_id.is_(None))
    )
    # procrastinate_jobs has no RLS; filter on this user's id explicitly.
    busy = await db.scalar(
        text(
            "select exists (select 1 from procrastinate_jobs where task_name = :task "
            "and status in ('todo', 'doing') and args->>'user_id' = :uid)"
        ),
        {"task": SCORE, "uid": str(user.id)},
    )
    return MatchingStatus(
        resumes=resumes,
        cover_letters=letters,
        scored=scored or 0,
        unscored=unscored or 0,
        last_scored_at=last,
        scoring=bool(busy),
        similarity=embedder() is not None,
        ai=bool(get_settings().anthropic_api_key),
    )


@router.post("/matching/rescore", response_model=Queued, status_code=status.HTTP_202_ACCEPTED)
async def rescore(user: User, _: UserDB):
    """Score every job again (e.g. after editing a resume elsewhere). Runs in the background."""
    await queue_scoring(user.id, "requested", delay=1)
    return Queued(queued=True)
