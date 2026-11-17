from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.modules.readiness.schemas import ReadinessOut, ReadinessSummary

# "duplicate": merged into another of the user's jobs (`duplicate_of`); listed nowhere, kept so it can be undone.
# review: added from a Google result by the extension, waiting for the user (POC, 2026-11-17)
Status = Literal["new", "seen", "ignored", "applied", "expired", "duplicate", "review"]
# "active" is new + seen: jobs still to decide on (not ignored, applied or expired).
StatusFilter = Literal["active", "new", "seen", "ignored", "applied", "expired", "review", "all"]
Lead = Literal["alert", "recommendation", "recruiter_invite", "company_feed", "job_board"]
# "naukri" covers recruiter invites (naukri_rdx) too; "company" every company career feed (milestone 9);
# "assistant" job lists an AI assistant mails (ai_assistant).
Source = Literal["linkedin", "naukri", "foundit", "company", "adzuna", "assistant"]
Band = Literal["strong", "good", "low", "filtered"]
# Jobs page tabs: top = strong + good (best first), other = low + filtered, unscored = not scored yet.
Tab = Literal["all", "top", "other", "unscored"]


class MatchSummary(BaseModel):
    """How well the job fits. `score` is the best resume's; `primary_score` the primary resume's."""

    band: Band
    score: int
    primary_score: int | None
    best_resume_id: UUID | None
    best_resume_label: str | None
    best_is_primary: bool
    provisional: bool = Field(
        description="Scored from the alert's few facts; paste the description to refine"
    )
    filter_reason: str | None


class FactorOut(BaseModel):
    key: str
    label: str
    score: int


class PointsLost(BaseModel):
    key: str = Field(
        description="A factor key, 'similarity' (wording), or a cap: 'clash' (another line of work), "
        "'industry' (industry experience not shown), 'not_a_fit' (you said so), 'track' (a hands-on role for a "
        "leader) or 'title_only' (no description yet); 'missing_skills' for skills your resumes don't show"
    )
    label: str
    points: int


class ResumeComparisonOut(BaseModel):
    """One resume's breakdown for a job, to compare with the suggested resume (the match's own breakdown)."""

    resume_id: UUID
    label: str
    score: int
    reason: str
    factors: list[FactorOut]
    points_lost: list[PointsLost]
    skills_have: list[str]
    skills_missing: list[str]
    key_skills_found: list[str]


class RankedResume(BaseModel):
    resume_id: UUID
    label: str
    score: int
    reason: str
    is_primary: bool


class RequirementOut(BaseModel):
    """One line of the description's requirements, checked against the suggested resume."""

    text: str
    status: Literal["met", "partly", "missing", "unclear"] = Field(
        description="unclear: it names no skill or degree that can be checked (judge it yourself)"
    )
    missing: list[str] = Field(
        default_factory=list, description="What it names that your resume doesn't show"
    )


class MatchDetail(MatchSummary):
    factors: list[FactorOut]
    strengths: list[str]
    gaps: list[str]
    ranking: list[RankedResume]
    cover_letter_id: UUID | None
    cover_letter_label: str | None
    search_profile_id: UUID | None
    search_profile_name: str | None
    points_lost: list[PointsLost] = Field(description="Where the points between the score and 100 went")
    skills_have: list[str] = Field(description="Skills the job asks for that your resume or profile shows")
    skills_missing: list[str] = Field(
        description="Skills the job asks for that your resume and profile don't"
    )
    key_skills_found: list[str] = Field(
        default_factory=list, description="Your search profile's key skills the job asks for (by meaning)"
    )
    must_haves: list[RequirementOut] = Field(
        default_factory=list, description="The description's must-haves (requirements sections), each checked"
    )
    preferred: list[RequirementOut] = Field(
        default_factory=list, description="Preferred only (nice to have): shown, never scored"
    )
    explained: bool = Field(description="False for a match scored before the breakdown existed")
    method: Literal["rules", "llm"]
    scored_at: datetime


class SourceOut(BaseModel):
    model_config = {"from_attributes": True}

    source: str
    url: str | None  # None for recruiter invites: they have no public page


class JobFacts(BaseModel):
    """Public posting data from the shared catalog."""

    model_config = {"from_attributes": True}

    id: UUID
    title: str
    company: str | None
    location: str | None
    work_model: str | None
    experience: str | None
    salary: str | None
    skills: list[str]
    posted_at: datetime | None
    sources: list[SourceOut]
    verified: bool = Field(
        description="False when only hand forwards or an AI assistant's list describe the job (no portal, feed or "
        "API has confirmed it yet): check it on the employer's page"
    )


class JobFactsDetail(JobFacts):
    description: str | None
    # "you" when the description shown is the one the user pasted, "alert" when it came with an email.
    description_source: Literal["you", "alert"] | None
    description_complete: bool
    about_company: str | None
    offer: str | None
    details: dict


class ApplicationBrief(BaseModel):
    id: UUID
    status: str
    applied_on: date
    follow_up_on: date | None


TodoKind = Literal["question", "description", "cover_letter", "gap", "expiry", "follow_up"]


class TodoOut(BaseModel):
    """Something the user has to do on this job (shown in amber), with a stable key."""

    key: str
    kind: TodoKind
    title: str
    detail: str


class OtherJobOut(BaseModel):
    """The other job of a duplicate pair, enough to compare the two side by side."""

    id: UUID
    status: Status
    lead: Lead
    first_seen_at: datetime
    applied_on: date | None
    job: JobFacts


class DuplicateOut(BaseModel):
    """Another of the user's jobs that is, or may be, the same role."""

    id: UUID = Field(description="The pair's id, for POST /jobs/{id}/duplicates/{pair_id}")
    kind: Literal["same", "likely", "agency"]
    reason: str
    similarity: int | None = Field(
        description="How alike the two descriptions are, in %; None if one is missing"
    )
    answer: Literal["same", "different"] | None
    merged: Literal["into_this", "into_other"] | None = Field(
        description="into_this: the other job was merged into this one; into_other: this one into the other"
    )
    other: OtherJobOut


class UserJobOut(BaseModel):
    """A job as one user received it. `id` is the user's job id, used in every /jobs/{id} route."""

    id: UUID
    status: Status
    lead: Lead
    outside_preference: bool
    has_apply_link: bool
    version: int
    first_seen_at: datetime
    last_seen_at: datetime
    expired_by: Literal["user", "auto"] | None
    may_have_expired: bool = Field(
        description="Active, and no alert has shown it for the admin's number of days"
    )
    todo: int = Field(description="How many things the user has to do on it (see todos on the detail)")
    application: ApplicationBrief | None
    job: JobFacts
    match: MatchSummary | None = Field(description="None until the job is scored (needs a resume)")
    readiness: ReadinessSummary | None = Field(
        None, description="Top matches only: ready, or how many blockers"
    )
    possible_duplicate: bool = Field(
        False, description="Possibly the same role as another of your jobs: decide on its page"
    )


class UserJobDetail(UserJobOut):
    job: JobFactsDetail
    match: MatchDetail | None
    readiness: ReadinessOut | None
    # Private: a Naukri recruiter invite's apply link signs the user in. Shown only to them; never opened
    # by the server.
    apply_url: str | None
    card_lines: list[str]  # what the alert said about the user, e.g. "2 connections"
    not_a_fit: list[str] = Field(
        description="The gaps for which you marked the job not a fit (empty if you didn't)"
    )
    todos: list[TodoOut]
    recruiter: str | None = Field(description="The recruiter the email named, when it named one")
    inbound_message_id: UUID | None
    duplicate_of: UUID | None = Field(description="The job this one was merged into (status duplicate)")
    duplicates: list[DuplicateOut] = Field(
        description="Jobs that are, or may be, the same role (ones you said are different are left out)"
    )
    not_for_me: str | None = Field(
        default=None, description='Your reason when you said "Not for me" (feedback/learning.py: REASONS)'
    )
    learned: str | None = Field(
        default=None,
        description='The learned preference this job falls under ("Jobs at Okta"): it scores at most 40',
    )


class JobList(BaseModel):
    items: list[UserJobOut]
    total: int
    limit: int
    offset: int


class JobStats(BaseModel):
    new: int
    active: int
    ignored: int
    applied: int
    expired: int
    review: int = 0  # added from Google results, waiting for Keep or Ignore
    last_7_days: int
    # Active jobs by tab.
    top: int
    other: int
    unscored: int
    # Active Top matches by readiness.
    ready: int
    needs_input: int


class UserJobPatch(BaseModel):
    status: Status
    version: int = Field(description="The version you last read; a stale version returns 409")


class SkillIn(BaseModel):
    skill: str = Field(min_length=1, max_length=80)

    @field_validator("skill")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Name the skill")
        return v


class NotAFitIn(BaseModel):
    gap: Literal["role", "exp", "core", "cloud", "ai", "domain", "loc", "skills", "comp", "other"] = Field(
        description="The gap that makes it not a fit (a factor key), or 'other'"
    )


class DuplicateAnswerIn(BaseModel):
    same: bool = Field(description="true: the same job (merged into one); false: different jobs (kept apart)")


class DescriptionIn(BaseModel):
    text: str = Field(min_length=50, max_length=50_000)
    version: int = Field(description="The version you last read; a stale version returns 409")

    @field_validator("text")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 50:
            raise ValueError("paste the whole description (at least 50 characters)")
        return v


Portal = Literal["linkedin", "naukri", "foundit"]


class PortalOut(BaseModel):
    id: Portal
    label: str


class GoogleSearchOut(BaseModel):
    role: str
    place: str | None
    queries: dict[Portal, str] = Field(description="The Google query for each portal's job pages")


class GoogleSearchesOut(BaseModel):
    portals: list[PortalOut]
    searches: list[GoogleSearchOut]
    roles_custom: bool = Field(False, description="The roles set on Find on Google (else the target roles)")


class FoundJobIn(BaseModel):
    """A job the user found on a portal in their own browser. BrewMyJob never opens the link."""

    url: str = Field(
        min_length=10, max_length=2000, description="The job's link on LinkedIn, Naukri or Foundit"
    )
    title: str = Field(min_length=2, max_length=300)
    company: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=50_000)

    @field_validator("url", "title", "company", "location")
    @classmethod
    def _trim(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

    @field_validator("description")
    @classmethod
    def _whole(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if v and len(v) < 50:
            raise ValueError("paste the whole description (at least 50 characters), or leave it empty")
        return v or None
