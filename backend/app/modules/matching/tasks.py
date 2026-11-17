"""Worker tasks: score a user's jobs (see service.score_user), and catch scores left behind."""

import logging
from uuid import UUID

import procrastinate
from sqlalchemy import select

from app.core.db import sessionmaker, user_scope
from app.core.worker import app
from app.modules.jobs.models import UserJob
from app.modules.matching.service import SCORE, queue_scoring, score_user, stale_scores
from app.modules.users.models import User

log = logging.getLogger("fitfirst.matching")
STALE = "matching.rescore_stale"


@app.task(name=SCORE, queue="match", retry=procrastinate.RetryStrategy(max_attempts=3, wait=30))
async def score(
    user_id: str,
    user_job_ids: list[str] | None = None,
    inbound_message_id: str | None = None,
    reason: str = "",
) -> None:
    uid = UUID(user_id)
    if inbound_message_id:
        async with user_scope(uid) as db:
            n = await score_user(db, uid, None, UUID(inbound_message_id))
    else:
        n = 0
        for part in await batches(uid, [UUID(i) for i in user_job_ids] if user_job_ids else None):
            async with user_scope(uid) as db:
                n += await score_user(db, uid, part)
    log.info("scoring (%s): %d jobs for user %s", reason or "requested", n, user_id)


BATCH = 40  # jobs per transaction


async def batches(user_id: UUID, ids: list[UUID] | None) -> list[list[UUID]]:
    """The jobs to score in parts of BATCH, each committed on its own (2026-11-15: one transaction for all 443
    of a user's jobs held their scores and match profile locked for minutes, and "Add to match profile" waited
    behind it)."""
    if ids is None:
        async with user_scope(user_id) as db:
            ids = list(await db.scalars(select(UserJob.id).order_by(UserJob.first_seen_at.desc())))
    return [ids[i : i + BATCH] for i in range(0, len(ids), BATCH)] or [[]]


async def rescore_stale_user(user_id: UUID) -> int:
    """Queue a rescore of the user's jobs whose description is newer than their score."""
    async with user_scope(user_id) as db:
        ids = await stale_scores(db)
    if ids:
        log.warning("rescoring %d jobs with a stale score for user %s", len(ids), user_id)
        await queue_scoring(user_id, "stale score", user_job_ids=ids, delay=0)
    return len(ids)


# A safety net (2026-11-12): a description's rescore once failed and the job kept its title-only score.
@app.periodic(cron="*/15 * * * *", periodic_id="rescore-stale")
@app.task(name=STALE, queue="match", queueing_lock=STALE)
async def rescore_stale(timestamp: int) -> None:
    async with sessionmaker()() as db:  # users has no RLS; each user's jobs are read inside user_scope
        users = list(await db.scalars(select(User.id)))
    total = sum([await rescore_stale_user(uid) for uid in users])
    if total:
        log.info("stale scores: %d jobs queued for rescoring", total)
