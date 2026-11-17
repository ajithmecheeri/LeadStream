"""What BrewMyJob learned from "Not for me" (milestone 13 A): list it, and forget any of it. The "Not for me"
button itself is on the job (POST /jobs/{id}/not-for-me, jobs/router.py)."""

from uuid import UUID

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from app.core.deps import User, UserDB
from app.core.errors import NotFound
from app.modules.feedback.models import LearnedPreference
from app.modules.feedback.schemas import LearnedOut
from app.modules.matching.service import queue_scoring

router = APIRouter(prefix="/preferences", tags=["feedback"])


@router.get("/learned", response_model=list[LearnedOut])
async def learned(user: User, db: UserDB):
    """Kinds of job you said weren't for you. Jobs like these score at most 40 (Other jobs)."""
    return list(await db.scalars(select(LearnedPreference).order_by(LearnedPreference.created_at.desc())))


@router.delete("/learned/{pref_id}", status_code=status.HTTP_204_NO_CONTENT)
async def forget(pref_id: UUID, user: User, db: UserDB):
    """Forget one: jobs it capped are scored on their merits again."""
    row = await db.get(LearnedPreference, pref_id)
    if row is None:
        raise NotFound("Learned preference")
    await db.delete(row)
    await db.flush()
    await queue_scoring(user.id, "learned preference removed")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
