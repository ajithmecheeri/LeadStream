"""Store a "Not for me" and what it teaches (learning.py), and read the user's learned preferences."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.candidate.models import CandidateProfile
from app.modules.catalog.models import Job
from app.modules.feedback.learning import Pref, learn
from app.modules.feedback.models import JobFeedback, LearnedPreference
from app.modules.jobs.models import UserJob
from app.modules.matching import taxonomy
from app.modules.profiles.models import SearchProfile


async def own_families(db: AsyncSession, user_id: UUID) -> set[str]:
    """The fields the user works in, from their headline and the roles their search profiles target."""
    cand = await db.get(CandidateProfile, user_id)
    roles = await db.scalars(select(SearchProfile.target_roles).where(SearchProfile.active))
    text = " ".join([cand.headline or "" if cand else "", *(r for rs in roles for r in rs)])
    return taxonomy.families(text)


async def prefs(db: AsyncSession) -> list[Pref]:
    rows = await db.scalars(select(LearnedPreference).order_by(LearnedPreference.created_at))
    return [Pref(p.kind, p.value, p.label) for p in rows]


async def record(
    db: AsyncSession, user_id: UUID, uj: UserJob, job: Job, reason: str, note: str | None
) -> list[LearnedPreference]:
    """Keep the feedback; add what it teaches (a preference already learned is kept as it was)."""
    fb = JobFeedback(user_id=user_id, user_job_id=uj.id, reason=reason, note=note)
    db.add(fb)
    await db.flush()
    taught = learn(reason, job.title, job.company, job.location, await own_families(db, user_id))
    added = []
    for p in taught:
        row = await db.scalar(
            insert(LearnedPreference)
            .values(user_id=user_id, kind=p.kind, value=p.value, label=p.label, feedback_id=fb.id)
            .on_conflict_do_nothing(index_elements=["user_id", "kind", "value"])
            .returning(LearnedPreference)
        )
        if row is not None:
            added.append(row)
    return added
