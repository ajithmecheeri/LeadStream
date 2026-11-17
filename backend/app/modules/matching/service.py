"""Score a user's jobs: gather their profile, resumes and jobs, refresh embeddings, store a JobMatch per job.

Called by the `matching.score` task (after an alert is read, or when a resume, profile or description
changes). Works inside the caller's user_scope session, so RLS applies throughout.
"""

import hashlib
import logging
from dataclasses import dataclass
from uuid import UUID

from procrastinate.exceptions import AlreadyEnqueued
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.config import get_settings
from app.core.vector import cosine
from app.core.worker import defer
from app.modules.candidate.models import CandidateProfile
from app.modules.catalog.models import Job
from app.modules.documents.models import CoverLetter, Resume
from app.modules.documents.reader import ResumeFacts, read
from app.modules.feedback import learning
from app.modules.feedback import service as feedback
from app.modules.feedback.learning import Pref
from app.modules.jobs.models import UserJob
from app.modules.llm.gateway import embed
from app.modules.matching import requirements, scoring, taxonomy
from app.modules.matching.models import JobMatch
from app.modules.notifications.service import alert_new_matches
from app.modules.profiles.models import SearchProfile
from app.modules.profiles.service import ensure_match_profiles

log = logging.getLogger("fitfirst.matching")

SCORE = "matching.score"
_EMBED_CHARS = 12_000
EMBED_AGAIN_SECONDS = 60  # Voyage's free-tier token limit is per minute
# In user_jobs.acknowledged: "not_a_fit:<factor>", the gap for which the user said the job isn't a fit.
NOT_A_FIT = "not_a_fit:"


async def stale_scores(db: AsyncSession) -> list[UUID]:
    """The user's jobs whose description came in after their score (a rescore that failed or never ran)."""
    return list(
        await db.scalars(
            select(UserJob.id)
            .join(JobMatch, JobMatch.user_job_id == UserJob.id)
            .where(UserJob.description_updated_at > JobMatch.scored_at)
        )
    )


async def queue_scoring(
    user_id: UUID,
    reason: str,
    user_job_ids: list[UUID] | None = None,
    inbound_message_id: UUID | None = None,
    delay: int = 3,
) -> None:
    """Queue a re-score. A full re-score is queued at most once at a time per user; the short delay lets the
    request that asked for it commit first, and gathers several quick edits into one run."""
    lock = None if (user_job_ids or inbound_message_id) else f"score-all:{user_id}"
    try:
        await defer(
            SCORE,
            queueing_lock=lock,
            schedule_in_seconds=delay or None,
            user_id=str(user_id),
            user_job_ids=[str(i) for i in user_job_ids] if user_job_ids else None,
            inbound_message_id=str(inbound_message_id) if inbound_message_id else None,
            reason=reason,
        )
    except AlreadyEnqueued:
        pass


def job_text(uj: UserJob, job: Job) -> str:
    """Everything known about the job as this user sees it (their pasted description wins)."""
    parts = [
        job.title,
        f"at {job.company}" if job.company else "",
        job.location or "",
        job.work_model or "",
        f"Experience {job.experience}" if job.experience else "",
        f"Salary {job.salary}" if job.salary else "",
        ("Skills: " + ", ".join(job.skills)) if job.skills else "",
        " ".join(f"{k}: {v}" for k, v in (job.details or {}).items() if isinstance(v, str)),
        uj.description or job.description or "",
    ]
    return "\n".join(p for p in parts if p).strip()


def _key(text: str) -> str:
    return hashlib.sha256(f"{get_settings().voyage_model}\n{text}".encode()).hexdigest()[:32]


async def _refresh_embeddings(
    db: AsyncSession, user_id: UUID, items: list[tuple[object, str]], purpose: str
) -> int | None:
    """Embed the items whose text changed since their last embedding, in order, up to about
    VOYAGE_TOKENS_PER_RUN tokens (a key without a payment method allows 10K a minute), so one scoring run stays
    short. Returns how many are still waiting, or None when this run embedded nothing (no key, cap, failure)."""
    stale = [
        (obj, text[:_EMBED_CHARS]) for obj, text in items if obj.embedding_key != _key(text[:_EMBED_CHARS])
    ]
    if not stale:
        return 0
    budget, take = get_settings().voyage_tokens_per_run * 3, 0  # about 3 characters a token
    while take < len(stale) and (take == 0 or budget - len(stale[take][1]) >= 0):
        budget -= len(stale[take][1])
        take += 1
    vectors = await embed(db, user_id, [t for _, t in stale[:take]], purpose)
    if vectors is None:
        return None
    for (obj, text), vec in zip(stale[:take], vectors, strict=True):
        obj.embedding, obj.embedding_key = vec, _key(text)
    return len(stale) - take


def _candidate(
    cand: CandidateProfile | None, facts: ResumeFacts, profiles: list[SearchProfile]
) -> scoring.Candidate:
    title = facts.current_title or facts.headline or (cand.headline if cand else None)
    fam_text = " ".join(
        [facts.current_title or "", facts.headline or "", (cand.headline or "") if cand else ""]
        + [r for p in profiles for r in p.target_roles]
    )
    location = (cand.current_location if cand else None) or facts.location
    return scoring.Candidate(
        years=(
            cand.years_experience if cand and cand.years_experience is not None else facts.years_experience
        ),
        level=taxonomy.seniority(title),
        families=taxonomy.families(fam_text),
        locations=[location] if location else [],
        expected_ctc_lakh=scoring.lakh(cand.expected_ctc) if cand else None,
        domains=list((cand.domains if cand else []) or facts.domains),
        track=taxonomy.track(title),
    )


def _profile(p: SearchProfile) -> scoring.ProfileInput:
    return scoring.ProfileInput(
        id=str(p.id),
        name=p.name,
        target_roles=p.target_roles,
        locations=p.locations,
        work_models=p.work_models,
        min_seniority=p.min_seniority,
        excluded_companies=p.excluded_companies,
        skills=[*(p.resume_skills or []), *(p.skills or [])],
        weights=p.weights,
        threshold=p.threshold,
        resume_id=str(p.resume_id) if p.resume_id else None,
        added_skills=list(p.skills or []),
    )


@dataclass
class _Context:
    """What every job of a user is scored against: the candidate, active profiles and resume facts."""

    candidate: scoring.Candidate
    profiles: list[scoring.ProfileInput]
    primary: Resume
    facts: dict[UUID, ResumeFacts]
    learned: list[Pref]  # from "Not for me" (milestone 13 A)

    def resume_input(self, r: Resume, uj: UserJob) -> scoring.ResumeInput:
        return scoring.ResumeInput(
            id=str(r.id),
            label=r.label,
            text=r.text.lower(),
            skills={s.lower() for s in self.facts[r.id].skills},
            similarity=cosine(r.embedding, uj.embedding),
        )


async def _context(db: AsyncSession, user_id: UUID, resumes: list[Resume]) -> _Context:
    # Every resume has its match profile, with the skills of the resume as it is now (2026-11-13). The skills
    # on the candidate profile no longer count for every resume: each resume stands with its own profile.
    await ensure_match_profiles(db, user_id)
    cand = await db.get(CandidateProfile, user_id)
    profiles = list(await db.scalars(select(SearchProfile).where(SearchProfile.active)))
    primary = next((r for r in resumes if r.is_primary), resumes[0])
    facts = {r.id: read(r.text) for r in resumes}
    return _Context(
        candidate=_candidate(cand, facts[primary.id], profiles),
        profiles=[_profile(p) for p in profiles],
        primary=primary,
        facts=facts,
        learned=await feedback.prefs(db),
    )


def _job_input(uj: UserJob, job: Job, text: str, learned: list[Pref]) -> scoring.JobInput:
    years = learning.years_asked(job.experience, text)
    # Requirements by section (user feedback 2026-11-16): preferred-only lines don't count as skills asked for.
    reqs = requirements.read(uj.description or job.description)
    for item in reqs.preferred:
        text = text.replace(item.text, " ")
    pref = learning.matching(learned, job.title, job.company, job.location, years)
    return scoring.JobInput(
        title=job.title,
        company=job.company,
        location=job.location,
        work_model=job.work_model,
        experience=job.experience,
        salary=job.salary,
        skills=list(job.skills or []),
        text=taxonomy.without_boilerplate(text).lower(),
        full_description=uj.description is not None or job.description_complete,
        not_a_fit=any(k.startswith(NOT_A_FIT) for k in uj.acknowledged or []),
        learned=pref.label if pref else None,
        years_short=learning.years_cut(learned, job.title, years),
        must=reqs.must,
        preferred=reqs.preferred,
    )


def _check(c: requirements.Check) -> dict:
    return {"text": c.text, "status": c.status, "missing": list(c.missing)}


async def compare_resume(
    db: AsyncSession, user_id: UUID, user_job_id: UUID, resume_id: UUID
) -> scoring.ResumeScore | None:
    """One resume's full breakdown for a job (factors, points lost, skills), judged against the same search
    profile as the job's match. Not saved: for comparing a resume with the suggested one. None when the job or
    resume doesn't exist or the job hasn't been scored."""
    resumes = list(
        await db.scalars(
            select(Resume)
            .options(undefer(Resume.embedding))
            .order_by(Resume.is_primary.desc(), Resume.created_at)
        )
    )
    resume = next((r for r in resumes if r.id == resume_id), None)
    match = await db.get(JobMatch, user_job_id)
    row = (
        await db.execute(
            select(UserJob, Job)
            .join(Job, Job.id == UserJob.job_id)
            .where(UserJob.id == user_job_id)
            .options(undefer(UserJob.embedding))
        )
    ).first()
    if resume is None or match is None or row is None:
        return None
    uj, job = row
    ctx = await _context(db, user_id, resumes)
    # The job's profile when it judges this resume (it has no resume, or it's this one's); else the resume's own.
    same = [
        p
        for p in ctx.profiles
        if p.id == str(match.search_profile_id) and p.resume_id in (None, str(resume_id))
    ]
    own = [p for p in ctx.profiles if p.resume_id == str(resume_id)]
    profiles = same or own or [p for p in ctx.profiles if p.resume_id is None] or [scoring.DEFAULT_PROFILE]
    v = scoring.score_job(
        _job_input(uj, job, job_text(uj, job), ctx.learned),
        ctx.candidate,
        profiles,
        [ctx.resume_input(resume, uj)],
    )
    return v.ranking[0] if v.ranking else None


async def score_user(
    db: AsyncSession,
    user_id: UUID,
    user_job_ids: list[UUID] | None = None,
    inbound_message_id: UUID | None = None,
) -> int:
    """Score the user's jobs (all of them, or the ones named). Returns how many were scored."""
    resumes = list(
        await db.scalars(
            select(Resume)
            .options(undefer(Resume.embedding))
            .order_by(Resume.is_primary.desc(), Resume.created_at)
        )
    )
    scope = select(UserJob.id)
    if user_job_ids is not None:
        scope = scope.where(UserJob.id.in_(user_job_ids))
    if inbound_message_id is not None:
        scope = scope.where(UserJob.inbound_message_id == inbound_message_id)
    if not resumes:
        # Nothing to score against: every job goes back to "not scored yet".
        await db.execute(delete(JobMatch).where(JobMatch.user_job_id.in_(scope)))
        return 0

    rows = (
        await db.execute(
            select(UserJob, Job)
            .join(Job, Job.id == UserJob.job_id)
            .where(UserJob.id.in_(scope))
            .options(undefer(UserJob.embedding))
        )
    ).all()
    if not rows:
        return 0
    letters = list(
        await db.scalars(
            select(CoverLetter)
            .options(undefer(CoverLetter.embedding))
            .order_by(CoverLetter.is_default.desc(), CoverLetter.created_at)
        )
    )
    texts = {uj.id: job_text(uj, job) for uj, job in rows}
    waiting = await _refresh_embeddings(
        db,
        user_id,
        [(r, r.text) for r in resumes]
        + [(c, c.text) for c in letters]
        + [(uj, texts[uj.id]) for uj, _ in rows],
        "matching",
    )
    if waiting:  # more to embed: score with what we have now, and again once the next part is embedded
        await queue_scoring(
            user_id,
            f"{waiting} embeddings waiting",
            user_job_ids=user_job_ids,
            inbound_message_id=inbound_message_id,
            delay=EMBED_AGAIN_SECONDS,
        )

    ctx = await _context(db, user_id, resumes)
    primary = ctx.primary

    for uj, job in rows:
        jin = _job_input(uj, job, texts[uj.id], ctx.learned)
        rins = [ctx.resume_input(r, uj) for r in resumes]
        v = scoring.score_job(jin, ctx.candidate, ctx.profiles, rins)
        by_id = {s.resume_id: s for s in v.ranking}
        best = v.ranking[0] if v.ranking else None
        letter = max(letters, key=lambda c: cosine(c.embedding, uj.embedding) or -1.0) if letters else None
        if letter is not None and all(cosine(c.embedding, uj.embedding) is None for c in letters):
            letter = letters[0]  # no embeddings: the default letter
        values = {
            "user_job_id": uj.id,
            "user_id": user_id,
            "search_profile_id": UUID(v.profile_id) if v.profile_id else None,
            "band": v.band,
            "score": v.score,
            "filter_reason": v.filter_reason,
            "factors": best.factors if best else {},
            "explain": {
                "lost": best.lost,
                "skills_have": best.skills_have,
                "skills_missing": best.skills_missing,
                "key_skills_found": best.key_skills_found,
                "must": [_check(c) for c in best.must],
                "preferred": [_check(c) for c in best.preferred],
            }
            if best
            else {},
            "ranking": [
                {"resume_id": s.resume_id, "label": s.label, "score": s.score, "reason": s.reason}
                for s in v.ranking
            ],
            "primary_resume_id": primary.id,
            "primary_score": by_id[str(primary.id)].score if str(primary.id) in by_id else None,
            "best_resume_id": UUID(best.resume_id) if best else None,
            "best_score": best.score if best else None,
            "cover_letter_id": letter.id if letter else None,
            "strengths": v.strengths,
            "gaps": v.gaps,
            "method": "rules",
            "provisional": v.provisional,
        }
        stmt = insert(JobMatch).values(**values)
        await db.execute(
            stmt.on_conflict_do_update(
                index_elements=[JobMatch.user_job_id],
                set_={k: stmt.excluded[k] for k in values if k != "user_job_id"}
                | {"scored_at": stmt.excluded.scored_at},
            )
        )
    # In a savepoint: a failed alert must never undo the scores above (2026-11-12, a pasted description's
    # rescore was lost when queueing its WhatsApp alert failed).
    try:
        async with db.begin_nested():
            await alert_new_matches(db, user_id, [uj.id for uj, _ in rows])
    except Exception:
        log.exception("WhatsApp alerts not queued for user %s; the scores are kept", user_id)
    log.info("scored %d jobs for user %s", len(rows), user_id)
    return len(rows)
