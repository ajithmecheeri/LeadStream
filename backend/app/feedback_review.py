"""Review "Not for me" feedback, to tune the matching rules (milestone 13 C, first step; a developer tool).

    python -m app.feedback_review                       # answers not reviewed yet, oldest first
    python -m app.feedback_review --all                 # every answer, reviewed ones too
    python -m app.feedback_review --done ID [ID…] --note "what was changed"

Each answer shows the job (title, company, place, source), the user's reason and note, the job's score now and
what the user's own learning made of it. An answer whose job still scores Good or Strong is one the rules got
wrong: those are listed with "still a match". IDs are the first 8 characters shown; --done stamps them reviewed.
It reads each user's rows inside that user's scope (RLS), and prints nothing else about the user than the email.
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.db import dispose_engine, sessionmaker, user_scope
from app.modules.catalog.models import Job, JobSource
from app.modules.feedback.learning import REASONS
from app.modules.feedback.models import JobFeedback, LearnedPreference
from app.modules.jobs.models import UserJob
from app.modules.matching.models import JobMatch
from app.modules.users.models import User


async def _users() -> list[tuple]:
    async with sessionmaker()() as db, db.begin():
        return list((await db.execute(select(User.id, User.email).order_by(User.created_at))).all())


async def review(show_all: bool) -> list[str]:
    out: list[str] = []
    for uid, email in await _users():
        async with user_scope(uid) as db:
            q = select(JobFeedback, UserJob, Job).join(UserJob, UserJob.id == JobFeedback.user_job_id)
            q = q.join(Job, Job.id == UserJob.job_id).order_by(JobFeedback.created_at)
            if not show_all:
                q = q.where(JobFeedback.reviewed_at.is_(None))
            for fb, uj, job in (await db.execute(q)).all():
                m = await db.scalar(select(JobMatch).where(JobMatch.user_job_id == uj.id))
                sources = await db.scalars(select(JobSource.source).where(JobSource.job_id == job.id))
                learned = await db.scalars(
                    select(LearnedPreference.label).where(LearnedPreference.feedback_id == fb.id)
                )
                taught = ", ".join(learned) or "nothing (recorded only)"
                score = f"{m.score} {m.band}" if m else "not scored"
                wrong = m is not None and m.band in ("strong", "good")
                lost = (
                    ", ".join(f"{k} {v}" for k, v in (m.explain or {}).get("lost", {}).items()) if m else ""
                )
                out += [
                    f"{str(fb.id)[:8]}  {fb.created_at:%Y-%m-%d}  {email}"
                    + (
                        f"  [reviewed {fb.reviewed_at:%Y-%m-%d}: {fb.review_note or ''}]"
                        if fb.reviewed_at
                        else ""
                    ),
                    f"  Job:     {job.title} · {job.company or '?'} · {job.location or '?'} · {', '.join(sources)}",
                    f"  Reason:  {REASONS.get(fb.reason, fb.reason)}" + (f" — {fb.note}" if fb.note else ""),
                    f"  Now:     {score}"
                    + ("  ← still a match" if wrong else "")
                    + (f"  (lost: {lost})" if lost else ""),
                    f"  Learned: {taught}",
                    "",
                ]
    return out or ["No feedback to review."]


async def mark_done(ids: list[str], note: str | None) -> list[str]:
    out: list[str] = []
    now = datetime.now(UTC)
    for uid, _ in await _users():
        async with user_scope(uid) as db:
            for fb in await db.scalars(select(JobFeedback)):
                if any(str(fb.id).startswith(i) for i in ids):
                    fb.reviewed_at, fb.review_note = now, note
                    out.append(f"{str(fb.id)[:8]} reviewed")
    return out or ["No feedback with those ids."]


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--all", action="store_true", help="include answers already reviewed")
    p.add_argument("--done", nargs="+", metavar="ID", help="mark these answers reviewed")
    p.add_argument("--note", help="what was changed for them (with --done)")
    args = p.parse_args()
    try:
        lines = await (mark_done(args.done, args.note) if args.done else review(args.all))
    finally:
        await dispose_engine()
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
