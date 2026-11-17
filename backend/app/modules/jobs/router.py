"""The user's jobs: every catalog job their alerts brought in, with their own status and match for each."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import User, UserDB
from app.core.errors import AppError, Conflict, NotFound
from app.modules.admin.service import AppValues
from app.modules.admin.service import load as load_app_settings
from app.modules.applications import service as applications
from app.modules.applications.models import Application
from app.modules.candidate.models import CandidateProfile
from app.modules.catalog.models import Job, JobSource
from app.modules.catalog.parsers.base import COMPANY_SITES
from app.modules.catalog.service import upsert_cards
from app.modules.documents.models import CoverLetter, Resume
from app.modules.feedback import learning
from app.modules.feedback import service as feedback
from app.modules.feedback.models import JobFeedback
from app.modules.feedback.schemas import NotForMeIn
from app.modules.jobs import duplicates, found
from app.modules.jobs.expiry import ACTIVE, may_have_expired, posting_doubt
from app.modules.jobs.linking import link_cards
from app.modules.jobs.models import JobDuplicate, UserJob
from app.modules.jobs.schemas import (
    ApplicationBrief,
    DescriptionIn,
    DuplicateAnswerIn,
    DuplicateOut,
    FactorOut,
    FoundJobIn,
    GoogleSearchesOut,
    GoogleSearchOut,
    JobFacts,
    JobFactsDetail,
    JobList,
    JobStats,
    Lead,
    MatchDetail,
    MatchSummary,
    NotAFitIn,
    OtherJobOut,
    PointsLost,
    PortalOut,
    RankedResume,
    RequirementOut,
    ResumeComparisonOut,
    SkillIn,
    Source,
    SourceOut,
    StatusFilter,
    Tab,
    TodoOut,
    UserJobDetail,
    UserJobOut,
    UserJobPatch,
)
from app.modules.matching.models import JobMatch
from app.modules.matching.service import NOT_A_FIT, compare_resume, job_text, queue_scoring, score_user
from app.modules.profiles.models import SearchProfile
from app.modules.profiles.schemas import FACTORS
from app.modules.profiles.service import add_skill_to, ensure_match_profiles
from app.modules.readiness.schemas import BlockerOut, ReadinessOut, ReadinessSummary
from app.modules.readiness.service import Readiness, evaluate, load_context, readiness_counts
from app.modules.users.models import User as UserRow

router = APIRouter(tags=["jobs"])

_SOURCES = {
    "linkedin": ["linkedin"],
    "naukri": ["naukri", "naukri_rdx"],
    "foundit": ["foundit"],
    "company": sorted(COMPANY_SITES),
    "adzuna": ["adzuna"],
    "assistant": ["ai_assistant"],
}
_TOP, _OTHER = ("strong", "good"), ("low", "filtered")
_LOST_LABELS = {
    **FACTORS,
    "similarity": "How closely your resume's wording matches the job",
    "clash": "A different line of work (score capped)",
    "title_only": "Only the title is known: add the description to confirm a Strong match",
    "industry": "Asks for industry experience your resumes don't show (score capped)",
    "not_a_fit": "You marked this job not a fit (score capped)",
    "learned": "Like jobs you said aren't for you (score capped)",
    "years_short": "Asks for fewer years than your level (10-20% off)",
    "track": "A hands-on role, while you lead teams (at most a Good match)",
    "must_have": "Must-haves in the description your resumes don't show",
    "degree": "Asks for a degree (PhD) your resumes don't show (score capped)",
}


def _lost_label(key: str, missing: list[str]) -> str:
    if key == "missing_skills":
        return "Skills it asks for that your resumes don't show" + (
            f": {', '.join(missing)}" if missing else ""
        )
    return _LOST_LABELS.get(key, key)


@dataclass
class _State:
    """What the user has to do on one job, worked out on read like readiness."""

    ready: Readiness | None
    application: Application | None
    may_expire: bool
    todos: list[TodoOut]


def _state(
    uj: UserJob,
    job: Job,
    sources: list[SourceOut],
    ready: Readiness | None,
    app: Application | None,
    values: AppValues,
    today: date,
) -> _State:
    doubt = posting_doubt(job, [s.source for s in sources], values)
    expire = may_have_expired(uj, values, doubt=doubt)
    todos: list[TodoOut] = []
    if uj.status in ACTIVE and ready is not None:
        todos += [TodoOut(key=b.key, kind=b.kind, title=b.title, detail=b.detail) for b in ready.blockers]
    if expire and doubt is not None and uj.confirmed_open_at is None:
        todos.append(
            TodoOut(
                key="expiry",
                kind="expiry",
                title=doubt.title,
                detail=f"{doubt.detail} Check the posting: mark it expired, or say it's still open.",
            )
        )
    elif expire:
        todos.append(
            TodoOut(
                key="expiry",
                kind="expiry",
                title="This job may have expired",
                detail=f"No alert has shown it for {values.job_expiry_warn_days} days or more. Check the posting: "
                "mark it expired, or say it's still open. Untouched, it moves to Expired after "
                f"{values.job_expiry_auto_days} days.",
            )
        )
    if uj.status == "applied" and app is not None and applications.follow_up_due(app, today):
        todos.append(
            TodoOut(
                key="follow_up",
                kind="follow_up",
                title="Follow up on this application",
                detail=f"You planned to follow up on {app.follow_up_on:%d %b %Y}.",
            )
        )
    return _State(ready, app, expire, todos)


def _brief(app: Application | None) -> ApplicationBrief | None:
    if app is None:
        return None
    return ApplicationBrief(
        id=app.id, status=app.status, applied_on=app.applied_on, follow_up_on=app.follow_up_on
    )


async def _applications(db: AsyncSession, user_job_ids: list[UUID]) -> dict[UUID, Application]:
    if not user_job_ids:
        return {}
    rows = await db.scalars(select(Application).where(Application.user_job_id.in_(user_job_ids)))
    return {a.user_job_id: a for a in rows}


def _like(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


async def _sources(db: AsyncSession, job_ids: list[UUID]) -> dict[UUID, list[SourceOut]]:
    out: dict[UUID, list[SourceOut]] = {i: [] for i in job_ids}
    if job_ids:
        rows = await db.scalars(
            select(JobSource).where(JobSource.job_id.in_(job_ids)).order_by(JobSource.first_seen_at)
        )
        for s in rows:
            out[s.job_id].append(SourceOut.model_validate(s))
    return out


def _match_fields(m: JobMatch) -> dict:
    labels = {r["resume_id"]: r["label"] for r in m.ranking}
    return {
        "band": m.band,
        "score": m.score,
        "primary_score": m.primary_score,
        "best_resume_id": m.best_resume_id,
        "best_resume_label": labels.get(str(m.best_resume_id)) if m.best_resume_id else None,
        "best_is_primary": m.best_resume_id is not None and m.best_resume_id == m.primary_resume_id,
        "provisional": m.provisional,
        "filter_reason": m.filter_reason,
    }


def _summary(
    uj: UserJob,
    job: Job,
    sources: list[SourceOut],
    match: JobMatch | None,
    st: _State,
    possible_duplicate: bool = False,
) -> UserJobOut:
    ready = st.ready
    return UserJobOut(
        id=uj.id,
        status=uj.status,
        lead=uj.lead,
        outside_preference=uj.outside_preference,
        has_apply_link=uj.apply_url is not None,
        version=uj.version,
        first_seen_at=uj.first_seen_at,
        last_seen_at=uj.last_seen_at,
        expired_by=uj.expired_by if uj.status == "expired" else None,
        may_have_expired=st.may_expire,
        todo=len(st.todos),
        application=_brief(st.application),
        job=JobFacts.model_validate({**_facts(job), "sources": sources}),
        match=MatchSummary(**_match_fields(match)) if match else None,
        readiness=ReadinessSummary(status=ready.status, blockers=len(ready.blockers)) if ready else None,
        possible_duplicate=possible_duplicate,
    )


def _facts(job: Job) -> dict:
    return {k: getattr(job, k) for k in JobFacts.model_fields if k != "sources"}


async def _get(db: AsyncSession, user_job_id: UUID, lock: bool = False) -> tuple[UserJob, Job]:
    # RLS limits user_jobs to the current user; another user's id simply isn't found.
    uj = await db.get(UserJob, user_job_id, with_for_update=lock)
    if uj is None:
        raise NotFound("Job")
    job = await db.get(Job, uj.job_id)
    assert job is not None  # the catalog never deletes
    return uj, job


async def _match_detail(db: AsyncSession, m: JobMatch) -> MatchDetail:
    letter = await db.get(CoverLetter, m.cover_letter_id) if m.cover_letter_id else None
    profile = await db.get(SearchProfile, m.search_profile_id) if m.search_profile_id else None
    explain = m.explain or {}
    return MatchDetail(
        points_lost=[
            PointsLost(key=k, label=_lost_label(k, explain.get("skills_missing", [])), points=v)
            for k, v in explain.get("lost", {}).items()
        ],
        skills_have=explain.get("skills_have", []),
        skills_missing=explain.get("skills_missing", []),
        key_skills_found=explain.get("key_skills_found", []),
        explained="lost" in explain,
        must_haves=[RequirementOut(**c) for c in explain.get("must", [])],
        preferred=[RequirementOut(**c) for c in explain.get("preferred", [])],
        **_match_fields(m),
        factors=[FactorOut(key=k, label=FACTORS.get(k, k), score=v) for k, v in m.factors.items()],
        strengths=m.strengths,
        gaps=m.gaps,
        ranking=[RankedResume(**r, is_primary=r["resume_id"] == str(m.primary_resume_id)) for r in m.ranking],
        cover_letter_id=letter.id if letter else None,
        cover_letter_label=letter.label if letter else None,
        search_profile_id=profile.id if profile else None,
        search_profile_name=profile.name if profile else None,
        method=m.method,
        scored_at=m.scored_at,
    )


async def _detail(db: AsyncSession, uj: UserJob, job: Job) -> UserJobDetail:
    sources = (await _sources(db, [job.id]))[job.id]
    match = await db.get(JobMatch, uj.id, populate_existing=True)
    mine = uj.description is not None
    facts = {
        **_facts(job),
        "sources": sources,
        "description": uj.description if mine else job.description,
        "description_source": "you" if mine else ("alert" if job.description else None),
        "description_complete": mine or job.description_complete,
        "about_company": job.about_company,
        "offer": job.offer,
        "details": job.details,
    }
    ready = evaluate(await load_context(db, uj.user_id), uj, job, match)
    app = await applications.for_job(db, uj.id)
    today = applications.today(await _timezone(db, uj.user_id))
    st = _state(uj, job, sources, ready, app, await load_app_settings(db), today)
    pairs = await _duplicates(db, uj)
    flagged = any(p.answer is None and p.merged is None for p in pairs)
    summary = _summary(uj, job, sources, None, st, flagged).model_dump(exclude={"job", "match", "readiness"})
    return UserJobDetail(
        **summary,
        todos=st.todos,
        recruiter=(job.details or {}).get("recruiter"),
        job=JobFactsDetail.model_validate(facts),
        match=await _match_detail(db, match) if match else None,
        readiness=ReadinessOut(
            status=ready.status, blockers=[BlockerOut(**b.__dict__) for b in ready.blockers]
        )
        if ready
        else None,
        apply_url=uj.apply_url,
        not_a_fit=[k.removeprefix(NOT_A_FIT) for k in uj.acknowledged or [] if k.startswith(NOT_A_FIT)],
        card_lines=uj.card_details.get("card_lines", []),
        inbound_message_id=uj.inbound_message_id,
        duplicate_of=uj.duplicate_of if uj.status == "duplicate" else None,
        duplicates=pairs,
        not_for_me=await db.scalar(
            select(JobFeedback.reason)
            .where(JobFeedback.user_job_id == uj.id)
            .order_by(JobFeedback.created_at.desc())
            .limit(1)
        ),
        learned=pref.label if (pref := await _learned(db, uj, job)) else None,
    )


async def _learned(db: AsyncSession, uj: UserJob, job: Job) -> learning.Pref | None:
    """The learned preference the job falls under, judged as matching judges it (matching/service.py)."""
    years = learning.years_asked(job.experience, job_text(uj, job))
    return learning.matching(await feedback.prefs(db), job.title, job.company, job.location, years)


async def _duplicates(db: AsyncSession, uj: UserJob) -> list[DuplicateOut]:
    pairs = await duplicates.pairs_of(db, uj.id)
    if not pairs:
        return []
    others = {
        o.id: (o, j)
        for o, j in (
            await db.execute(
                select(UserJob, Job)
                .join(Job, Job.id == UserJob.job_id)
                .where(UserJob.id.in_([other_id for _, other_id in pairs]))
            )
        ).all()
    }
    sources = await _sources(db, [j.id for _, j in others.values()])
    apps = await _applications(db, list(others))
    out = []
    for p, other_id in pairs:
        other, job = others[other_id]
        merged = (
            "into_this"
            if other.status == "duplicate" and other.duplicate_of == uj.id
            else "into_other"
            if uj.status == "duplicate" and uj.duplicate_of == other.id
            else None
        )
        app = apps.get(other.id)
        out.append(
            DuplicateOut(
                id=p.id,
                kind=p.kind,
                reason=p.reason,
                similarity=p.similarity,
                answer=p.answer,
                merged=merged,
                other=OtherJobOut(
                    id=other.id,
                    status=other.status,
                    lead=other.lead,
                    first_seen_at=other.first_seen_at,
                    applied_on=app.applied_on if app else None,
                    job=JobFacts.model_validate({**_facts(job), "sources": sources[job.id]}),
                ),
            )
        )
    return out


async def _timezone(db: AsyncSession, user_id: UUID) -> str:
    return await db.scalar(select(UserRow.timezone).where(UserRow.id == user_id)) or "UTC"


def _tab(stmt: Select, tab: Tab) -> Select:
    if tab == "top":
        return stmt.where(JobMatch.band.in_(_TOP))
    if tab == "other":
        return stmt.where(JobMatch.band.in_(_OTHER))
    if tab == "unscored":
        return stmt.where(JobMatch.user_job_id.is_(None))
    return stmt


def _filter(
    stmt: Select,
    status: StatusFilter,
    lead: Lead | None,
    source: Source | None,
    q: str | None,
    day_from: date | None,
    day_to: date | None,
    tz: str,
) -> Select:
    if status == "active":
        stmt = stmt.where(UserJob.status.in_(ACTIVE))
    elif status == "all":
        stmt = stmt.where(UserJob.status != "duplicate")
    else:
        stmt = stmt.where(UserJob.status == status)
    if lead:
        stmt = stmt.where(UserJob.lead == lead)
    if source:
        stmt = stmt.where(exists().where(JobSource.job_id == Job.id, JobSource.source.in_(_SOURCES[source])))
    if q and q.strip():
        pattern = _like(" ".join(q.split()))
        stmt = stmt.where(
            or_(
                Job.title.ilike(pattern),
                Job.company.ilike(pattern),
                Job.location.ilike(pattern),
                func.array_to_string(Job.skills, " ").ilike(pattern),
            )
        )
    # Dates are the user's calendar days (users.timezone), not UTC days.
    local_day = func.date(func.timezone(tz, UserJob.first_seen_at))
    if day_from:
        stmt = stmt.where(local_day >= day_from)
    if day_to:
        stmt = stmt.where(local_day <= day_to)
    return stmt


@router.get("/jobs", response_model=JobList)
async def list_jobs(
    user: User,
    db: UserDB,
    status: StatusFilter = "active",
    tab: Annotated[Tab, Query(description="top: best matches first; other: weak or ruled out")] = "all",
    readiness: Annotated[
        Literal["ready", "needs_input"] | None,
        Query(description="Top matches that are ready, or need your input"),
    ] = None,
    lead: Lead | None = None,
    source: Source | None = None,
    q: Annotated[str | None, Query(max_length=100, description="Title, company, location or skill")] = None,
    day_from: Annotated[
        date | None, Query(alias="from", description="First seen on or after (your date)")
    ] = None,
    day_to: Annotated[
        date | None, Query(alias="to", description="First seen on or before (your date)")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    if day_from and day_to and day_from > day_to:
        raise AppError(422, "validation_error", "'from' must be on or before 'to'")
    tz = await _timezone(db, user.id)
    base = (
        select(UserJob, Job, JobMatch)
        .join(Job, Job.id == UserJob.job_id)
        .outerjoin(JobMatch, JobMatch.user_job_id == UserJob.id)
    )
    if readiness:
        tab = "top"  # readiness exists for Top matches only
    base = _tab(_filter(base, status, lead, source, q, day_from, day_to, tz), tab)
    order = [UserJob.first_seen_at.desc(), UserJob.id]
    if tab in ("top", "other"):
        order = [JobMatch.score.desc(), *order]
    elif status == "expired":
        order = [UserJob.expired_at.desc().nulls_last(), *order]
    ctx = await load_context(db, user.id)
    if readiness:
        # Readiness is worked out per job, so this filter runs here; Top matches are a short list.
        rows = (await db.execute(base.order_by(*order))).all()
        every = [(uj, job, m, evaluate(ctx, uj, job, m)) for uj, job, m in rows]
        every = [r for r in every if r[3] and r[3].status == readiness]
        total, page = len(every), every[offset : offset + limit]
    else:
        total = await db.scalar(select(func.count()).select_from(base.subquery()))
        rows = (await db.execute(base.order_by(*order).limit(limit).offset(offset))).all()
        page = [(uj, job, m, evaluate(ctx, uj, job, m)) for uj, job, m in rows]
    sources = await _sources(db, [job.id for _, job, _, _ in page])
    apps = await _applications(db, [uj.id for uj, _, _, _ in page])
    values, today = await load_app_settings(db), applications.today(tz)
    flagged = await duplicates.possible(db, [uj.id for uj, _, _, _ in page])
    return JobList(
        items=[
            _summary(
                uj,
                job,
                sources[job.id],
                m,
                _state(uj, job, sources[job.id], r, apps.get(uj.id), values, today),
                uj.id in flagged,
            )
            for uj, job, m, r in page
        ],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/jobs/stats", response_model=JobStats)
async def job_stats(user: User, db: UserDB):
    week_ago = datetime.now(UTC) - timedelta(days=7)
    active = UserJob.status.in_(ACTIVE)
    row = (
        await db.execute(
            select(
                func.count().filter(UserJob.status == "new"),
                func.count().filter(active),
                func.count().filter(UserJob.status == "ignored"),
                func.count().filter(UserJob.status == "applied"),
                func.count().filter(UserJob.status == "expired"),
                func.count().filter(UserJob.first_seen_at >= week_ago, active),
                func.count().filter(UserJob.status == "review"),
                func.count().filter(active, JobMatch.band.in_(_TOP)),
                func.count().filter(active, JobMatch.band.in_(_OTHER)),
                func.count().filter(active, JobMatch.user_job_id.is_(None)),
            )
            .select_from(UserJob)
            .outerjoin(JobMatch, JobMatch.user_job_id == UserJob.id)
        )
    ).one()
    ready, needs_input = await readiness_counts(db, user.id)
    return JobStats(
        ready=ready,
        needs_input=needs_input,
        new=row[0],
        active=row[1],
        ignored=row[2],
        applied=row[3],
        expired=row[4],
        last_7_days=row[5],
        review=row[6],
        top=row[7],
        other=row[8],
        unscored=row[9],
    )


@router.get("/jobs/google-searches", response_model=GoogleSearchesOut)
async def google_searches(user: User, db: UserDB):
    """Ready-made Google searches for LinkedIn, Naukri and Foundit job pages, from your roles for Google (the ones
    Google Alerts use too; else your target roles) and job locations. You run them in your own browser; BrewMyJob
    never reads those sites."""
    profiles = list(
        await db.scalars(select(SearchProfile).where(SearchProfile.active).order_by(SearchProfile.created_at))
    )
    candidate = await db.get(CandidateProfile, user.id)
    own = list(candidate.alert_roles or []) if candidate else []
    roles = own or [r for p in profiles for r in p.target_roles]
    places = [*(candidate.job_locations if candidate else []), *(x for p in profiles for x in p.locations)]
    return GoogleSearchesOut(
        portals=[PortalOut(id=k, label=label) for k, (label, _) in found.PORTALS.items()],  # type: ignore[arg-type]
        roles_custom=bool(own),
        searches=[
            GoogleSearchOut(role=s.role, place=s.place, queries=s.queries)  # type: ignore[arg-type]
            for s in found.searches(roles, places)
        ],
    )


@router.post("/jobs/found", response_model=UserJobDetail, status_code=201)
async def add_found_job(body: FoundJobIn, user: User, db: UserDB):
    """Add a job you found on LinkedIn, Naukri or Foundit. The link is only read for the portal's job id; the
    page is never opened. With the description pasted, the score is a full one."""
    try:
        card = found.card(body.url, body.title, body.company, body.location)
    except found.NotAJobLink as e:
        raise AppError(422, "not_a_job_link", str(e), [{"field": "url", "message": str(e)}]) from None
    # Typed by hand, like a hand-forwarded email: unverified, and it never changes a job the catalog knows.
    [match] = await upsert_cards(db, [card], verified=False)
    await link_cards(db, user.id, [card], [match])
    uj = await db.scalar(select(UserJob).where(UserJob.job_id == match.job_id))
    if uj is None:
        raise NotFound("Job")
    if uj.status == "duplicate" and uj.duplicate_of:  # merged into one the user already has: show that one
        uj = await db.get(UserJob, uj.duplicate_of) or uj
    if body.description:
        uj.description = body.description
        uj.description_updated_at = datetime.now(UTC)
        uj.version += 1
    await db.flush()
    await db.refresh(uj)
    await queue_scoring(user.id, "job added", user_job_ids=[uj.id])
    job = await db.get(Job, uj.job_id)
    return await _detail(db, uj, job)


@router.get("/jobs/{user_job_id}", response_model=UserJobDetail)
async def get_job(user_job_id: UUID, _: User, db: UserDB):
    uj, job = await _get(db, user_job_id)
    return await _detail(db, uj, job)


@router.patch("/jobs/{user_job_id}", response_model=UserJobDetail)
async def patch_job(user_job_id: UUID, body: UserJobPatch, _: User, db: UserDB):
    """Mark a job seen, ignored, applied or expired, or restore it (status "seen").

    Applied records an application (you apply yourself; this keeps track). Leaving Applied removes that
    application, which is refused once it has updates. Expired here is your choice and stays even when a new
    alert shows the job again.
    """
    uj, job = await _get(db, user_job_id, lock=True)
    if body.version != uj.version:
        raise Conflict("version_conflict", "This job was changed elsewhere. Reload and try again.")
    if body.status != uj.status and "duplicate" in (body.status, uj.status):
        raise AppError(
            422,
            "duplicate",
            "Duplicates are merged and undone with Same job / Different job on the job's page",
        )
    if body.status == "review" and uj.status != "review":
        raise AppError(422, "review", "Only jobs added from Google results wait for review")
    if body.status != uj.status:
        if uj.status == "applied":
            await applications.undo_applied(db, uj)
        if body.status == "applied":
            await applications.mark_applied(db, uj)
        if body.status == "expired":
            uj.expired_at, uj.expired_by = datetime.now(UTC), "user"
        elif uj.status == "expired":
            # Back to active: the user says it's still open, so the expiry clock restarts.
            uj.expired_at, uj.expired_by = None, None
            uj.confirmed_open_at = datetime.now(UTC)
        uj.status = body.status
        uj.version += 1
    await db.flush()
    await db.refresh(uj)
    return await _detail(db, uj, job)


@router.post("/jobs/{user_job_id}/not-for-me", response_model=UserJobDetail)
async def not_for_me(user_job_id: UUID, body: NotForMeIn, user: User, db: UserDB):
    """Not for me, and why (milestone 13 A). The job is ignored. A reason about its company, city, field or level
    is learned: jobs like it score at most 40 from now on (Other jobs), listed on Profile to undo."""
    uj, job = await _get(db, user_job_id, lock=True)
    if body.version != uj.version:
        raise Conflict("version_conflict", "This job was changed elsewhere. Reload and try again.")
    if uj.status in ("applied", "duplicate"):
        raise AppError(422, "not_active", "Only a job you haven't applied to can be marked not for me")
    if uj.status != "ignored":
        uj.status = "ignored"
        uj.version += 1
    added = await feedback.record(db, user.id, uj, job, body.reason, body.note)
    await db.flush()
    await score_user(db, user.id, user_job_ids=[uj.id])
    if added:
        await queue_scoring(user.id, "learned from not for me")  # other jobs like it
    await db.refresh(uj)
    return await _detail(db, uj, job)


@router.post("/jobs/{user_job_id}/still-open", response_model=UserJobDetail)
async def still_open(user_job_id: UUID, _: User, db: UserDB):
    """You checked the posting and it's still open: clears "May have expired" and restarts the clock."""
    uj, job = await _get(db, user_job_id, lock=True)
    if uj.status not in ACTIVE:
        raise AppError(422, "not_active", "Only an active job can be marked still open")
    uj.confirmed_open_at = datetime.now(UTC)
    uj.version += 1
    await db.flush()
    await db.refresh(uj)
    return await _detail(db, uj, job)


@router.get("/jobs/{user_job_id}/resumes/{resume_id}", response_model=ResumeComparisonOut)
async def compare_with_resume(user_job_id: UUID, resume_id: UUID, user: User, db: UserDB):
    """How another of your resumes does on this job, factor by factor, against the same search profile as the
    job's match. Nothing is saved; the suggested resume stays the one with the best score."""
    s = await compare_resume(db, user.id, user_job_id, resume_id)
    if s is None:
        raise NotFound("Scored job or resume")
    return ResumeComparisonOut(
        resume_id=UUID(s.resume_id),
        label=s.label,
        score=s.score,
        reason=s.reason,
        factors=[FactorOut(key=k, label=FACTORS.get(k, k), score=v) for k, v in s.factors.items()],
        points_lost=[
            PointsLost(key=k, label=_lost_label(k, s.skills_missing), points=v) for k, v in s.lost.items()
        ],
        skills_have=s.skills_have,
        skills_missing=s.skills_missing,
        key_skills_found=s.key_skills_found,
    )


@router.post("/jobs/{user_job_id}/skills", response_model=UserJobDetail)
async def i_have_this_skill(user_job_id: UUID, body: SkillIn, user: User, db: UserDB):
    """Add a skill you really have to the match profile of the resume this job was matched with (its suggested
    resume; else your primary resume's). This job is re-scored now, the rest in the background.

    Tailored resumes and cover letters may claim only what your resumes and profiles support, so add only
    skills you can back up. The match profile lists the skills its resume doesn't show yet, to add there too.
    """
    uj, job = await _get(db, user_job_id)
    await ensure_match_profiles(db, user.id)
    match = await db.get(JobMatch, uj.id)
    resume_id = match.best_resume_id if match else None
    if resume_id is None:
        resume_id = await db.scalar(select(Resume.id).order_by(Resume.is_primary.desc(), Resume.created_at))
    profile = (
        await db.scalar(select(SearchProfile).where(SearchProfile.resume_id == resume_id).with_for_update())
        if resume_id
        else None
    )
    if profile is None:
        raise AppError(422, "no_resume", "Add a resume first: skills go to the match profile of a resume")
    if await add_skill_to(db, profile, body.skill):
        await score_user(db, user.id, user_job_ids=[uj.id])
        await queue_scoring(user.id, "skill added")
    return await _detail(db, uj, job)


@router.post("/jobs/{user_job_id}/not-a-fit", response_model=UserJobDetail)
async def not_a_fit(user_job_id: UUID, body: NotAFitIn, user: User, db: UserDB):
    """Say the job isn't a fit because of a gap (the industry, the skills…). It is re-scored at most 40 and
    moves to Other jobs; DELETE undoes it."""
    uj, job = await _get(db, user_job_id)
    key = f"{NOT_A_FIT}{body.gap}"
    if key not in (uj.acknowledged or []):
        uj.acknowledged = [*(uj.acknowledged or []), key]
        await db.flush()
        await score_user(db, user.id, user_job_ids=[uj.id])
    return await _detail(db, uj, job)


@router.delete("/jobs/{user_job_id}/not-a-fit", response_model=UserJobDetail)
async def undo_not_a_fit(user_job_id: UUID, user: User, db: UserDB):
    """Take back "not a fit": the job is re-scored on its merits."""
    uj, job = await _get(db, user_job_id)
    kept = [k for k in uj.acknowledged or [] if not k.startswith(NOT_A_FIT)]
    if kept != (uj.acknowledged or []):
        uj.acknowledged = kept
        await db.flush()
        await score_user(db, user.id, user_job_ids=[uj.id])
    return await _detail(db, uj, job)


@router.post("/jobs/{user_job_id}/description", response_model=UserJobDetail)
async def paste_description(user_job_id: UUID, body: DescriptionIn, user: User, db: UserDB):
    """Paste the full job description from the portal. It is stored for you only, and the job is re-scored."""
    uj, job = await _get(db, user_job_id, lock=True)
    if body.version != uj.version:
        raise Conflict("version_conflict", "This job was changed elsewhere. Reload and try again.")
    uj.description = body.text
    uj.description_updated_at = datetime.now(UTC)
    uj.version += 1
    await db.flush()
    await db.refresh(uj)
    await queue_scoring(user.id, "description pasted", user_job_ids=[uj.id])
    return await _detail(db, uj, job)


@router.post("/jobs/{user_job_id}/duplicates/{pair_id}", response_model=UserJobDetail)
async def answer_duplicate(user_job_id: UUID, pair_id: UUID, body: DuplicateAnswerIn, _: User, db: UserDB):
    """Say whether a possible duplicate is the same job. Same merges the two: the applied one, else the earlier
    one, is kept and the other leaves your lists. Different keeps both (undoing a merge BrewMyJob made) and the
    pair isn't flagged again. Returns this job as it is now (status duplicate if it was merged away)."""
    uj, job = await _get(db, user_job_id)
    pair = await db.get(JobDuplicate, pair_id, with_for_update=True)
    if pair is None or user_job_id not in (pair.user_job_id, pair.other_id):
        raise NotFound("Possible duplicate")
    await duplicates.answer(db, pair, body.same)
    await db.refresh(uj)
    return await _detail(db, uj, job)
