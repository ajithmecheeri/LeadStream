"""Readiness: is a matched job ready to apply for, or what does the user still need to do?

Worked out from current data on every read, so it can't go stale: the job's match, the answer bank, the
candidate profile, the cover-letter library and whether the full description is in. Only Top matches (strong
and good) get a readiness; other jobs aren't worth the user's time yet.

"Manual only" (online assessments, login walls, unsupported application systems) needs to see the application
form, which arrives with the browser extension; until then no job is classified that way.
"""

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.candidate.models import CandidateProfile
from app.modules.catalog.models import Job
from app.modules.documents.models import CoverLetter
from app.modules.jobs.models import UserJob
from app.modules.matching import taxonomy
from app.modules.matching.models import JobMatch
from app.modules.matching.scoring import TRACK_ROLE
from app.modules.profiles.schemas import FACTORS
from app.modules.readiness.models import Answer
from app.modules.readiness.questions import STANDARD

TOP_BANDS = ("strong", "good")
GAP_BELOW = 45  # a factor under this is a gap worth a look


@dataclass
class Blocker:
    key: str  # stable: "question:notice_period", "description", "cover_letter", "gap:skills"
    kind: str  # question | description | cover_letter | gap
    title: str
    detail: str
    question: str | None = None


@dataclass
class Readiness:
    status: str  # ready | needs_input
    blockers: list[Blocker] = field(default_factory=list)


@dataclass
class Context:
    """What every job's readiness is checked against; loaded once per request."""

    candidate: CandidateProfile | None
    answers: dict[str, Answer]
    cover_letters: int

    def answered(self, key: str) -> bool:
        if key in self.answers:
            return True
        std = next((s for s in STANDARD if s.key == key), None)
        return bool(std and self.candidate and std.from_profile(self.candidate))


async def load_context(db: AsyncSession, user_id: UUID) -> Context:
    answers = {a.key: a for a in await db.scalars(select(Answer).where(Answer.search_profile_id.is_(None)))}
    letters = await db.scalar(select(func.count()).select_from(CoverLetter)) or 0
    return Context(await db.get(CandidateProfile, user_id), answers, letters)


def _listed(items: list[str], most: int = 6) -> str:
    shown = ", ".join(items[:most])
    return shown + (f" and {len(items) - most} more" if len(items) > most else "")


def _gap_detail(key: str, uj: UserJob, job: Job, match: JobMatch, ctx: Context) -> str:
    """What the gap is, naming what the job asks for where it can, so the user can judge it: address it, or
    say the job isn't a fit."""
    years = ctx.candidate.years_experience if ctx.candidate else None
    missing = (match.explain or {}).get("skills_missing", [])
    text = uj.description or job.description or ""
    terms = taxonomy.industry_terms(text)
    fields = taxonomy.domains(f"{job.company or ''} {text}")
    if terms:
        domain = f"The job asks for industry experience your resumes don't show: {_listed(terms)}."
    elif fields:
        domain = f"The job is in {_listed(fields)}, which is new for you."
    else:
        domain = "The industry is new for you."
    first = taxonomy.title_main(job.title)
    role = (
        f"“{first}” is a hands-on (individual contributor) role, while your current role leads teams. A grade in "
        "the title (a bank's “VP”) is not a leadership role."
        if taxonomy.track(job.title) == "ic" and (match.factors or {}).get("role", 100) <= TRACK_ROLE
        else "The title doesn't line up closely with your background or seniority."
    )
    return {
        "role": role,
        "exp": f"The job asks for {job.experience}"
        + (f"; you have {years} years." if years is not None else "."),
        "skills": f"Not in your resumes: {_listed(missing)}."
        if missing
        else "Some of the skills it lists aren't in your resumes.",
        "domain": domain,
        "comp": f"The salary ({job.salary}) may be below your expected CTC.",
        "loc": "The location doesn't match your preferences.",
    }.get(key, f"Your resumes say little about {FACTORS.get(key, key)}.")


def evaluate(ctx: Context, uj: UserJob, job: Job, match: JobMatch | None) -> Readiness | None:
    """The job's readiness, or None when it isn't a Top match."""
    if match is None or match.band not in TOP_BANDS:
        return None
    blockers: list[Blocker] = []

    for std in STANDARD:
        if std.required and not ctx.answered(std.key):
            blockers.append(
                Blocker(
                    f"question:{std.key}",
                    "question",
                    std.question,
                    "Application forms almost always ask this. Answer once; every job reuses it.",
                    std.question,
                )
            )

    job_cities, truncated = taxonomy.cities(job.location)
    home, _ = taxonomy.cities(ctx.candidate.current_location if ctx.candidate else None)
    remote = taxonomy.is_remote(job.location) or (job.work_model or "").lower() == "remote"
    if (
        job_cities
        and home
        and not truncated
        and not remote
        and not (job_cities & home)
        and not ctx.answered("relocation")
    ):
        city = job.location or "the job's city"
        blockers.append(
            Blocker(
                "question:relocation",
                "question",
                f"Are you willing to relocate to {city}?",
                "The job is outside your current city.",
                "Are you willing to relocate?",
            )
        )

    if uj.description is None and not job.description_complete:
        blockers.append(
            Blocker(
                "description",
                "description",
                "Paste the full job description",
                "The alert only had the title and a few facts. The full description sharpens the score and is "
                "what the tailored resume and cover letter are written against.",
            )
        )

    if ctx.cover_letters == 0:
        blockers.append(
            Blocker(
                "cover_letter",
                "cover_letter",
                "Add a cover letter",
                "Many applications ask for one. Add yours on the Profile page; the best fit is suggested per job.",
            )
        )

    for key, score in (match.factors or {}).items():
        if score < GAP_BELOW and f"gap:{key}" not in (uj.acknowledged or []):
            blockers.append(
                Blocker(
                    f"gap:{key}",
                    "gap",
                    f"Gap: {FACTORS.get(key, key)}",
                    _gap_detail(key, uj, job, match, ctx),
                )
            )

    return Readiness("needs_input" if blockers else "ready", blockers)


async def readiness_counts(db: AsyncSession, user_id: UUID) -> tuple[int, int]:
    """(ready, needs_input) among the user's active Top matches."""
    ctx = await load_context(db, user_id)
    rows = (
        await db.execute(
            select(UserJob, Job, JobMatch)
            .join(Job, Job.id == UserJob.job_id)
            .join(JobMatch, JobMatch.user_job_id == UserJob.id)
            .where(UserJob.status.in_(("new", "seen")), JobMatch.band.in_(TOP_BANDS))
        )
    ).all()
    states = [r.status for r in (evaluate(ctx, uj, job, m) for uj, job, m in rows) if r]
    return states.count("ready"), states.count("needs_input")
