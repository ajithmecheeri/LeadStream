from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

Ats = Literal[
    "greenhouse", "lever", "ashby", "smartrecruiters", "workday", "oracle", "eightfold", "careers_page"
]


class SourceRunOut(BaseModel):
    ran_at: datetime
    found: int  # India jobs the source listed (or that arrived from it)
    added: int  # new to you
    skipped: int  # left out: not your level or field
    error: str | None


class CompanyOut(BaseModel):
    id: UUID  # the employer's id in the job search service (what DELETE takes)
    name: str
    ats: Ats | None  # None while the job search service can't be reached
    board: str | None
    board_url: str | None
    jobs_india: int | None
    last_checked_at: datetime | None
    last_error: str | None
    my_jobs: int  # your jobs from this company
    last_run: SourceRunOut | None


class SuggestedCompanyOut(BaseModel):
    name: str
    ats: Ats
    board: str
    watching: bool


class AdzunaOut(BaseModel):
    configured: bool  # the job search service has an Adzuna key
    searches: list[str]  # "VP Engineering in Bengaluru", from your search profiles
    last_run: SourceRunOut | None


class LastCheckOut(BaseModel):
    """The latest check of your sources, all companies and Adzuna together."""

    ran_at: datetime  # when it finished
    sources: int  # companies (and Adzuna) checked
    found: int  # India jobs they listed
    added: int  # new to you
    skipped: int  # left out: not your level or field
    errors: int  # sources that couldn't be read


class LastRunOut(BaseModel):
    """The job search service's last run that brought jobs, and what of it fits you."""

    ran_at: datetime
    jobs: int  # jobs pulled (new and changed), for every user
    new: int  # of them, jobs BrewMyJob had not seen before
    updated: int  # of them, known jobs the employer changed or reposted
    closed: int  # jobs the employers took down
    fit: int  # pulled jobs that fit your profile (your followed companies at your level and field, or job-API
    # jobs that pass your search profiles)
    added: int  # of those, new to your list
    top_matches: int  # of the new ones, in your Top matches now


class ConnectorOut(BaseModel):
    """One hiring system or job API in the job search service, over the last 24 hours."""

    connector: str
    configured: bool
    boards: int
    last_run_at: datetime | None
    runs_24h: int
    failures_24h: int
    last_error: str | None


class SourcesOut(BaseModel):
    companies: list[CompanyOut]
    suggestions: list[SuggestedCompanyOut]
    adzuna: AdzunaOut
    checking: bool  # a check is queued or running
    last_check: LastCheckOut | None
    last_run: LastRunOut | None  # the service's last run that pulled jobs (None: none yet)
    next_check_at: datetime  # the next scheduled read of the boards
    check_times: str  # on the user's clock (users.timezone): "every 3 hours (next at 09:30 IST)"
    service_available: bool  # False: the job search service can't be reached right now
    connectors: list[ConnectorOut]


class LookupIn(BaseModel):
    query: str = Field(min_length=2, max_length=300)  # a company name or a careers-page link


class FoundBoardOut(BaseModel):
    ats: Ats
    board: str
    board_url: str
    india: int
    total: int
    sample: list[str]


class CompanyIn(BaseModel):
    """Follow a board found by the lookup (`ats` + `board`), or one given by its careers link (`url`)."""

    name: str = Field(min_length=1, max_length=120)
    ats: Ats | None = None
    board: str | None = Field(None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
    url: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def _one_way(self):
        if not self.url and not (self.ats and self.board):
            raise ValueError("Give the board found, or a careers-page link")
        return self


class SuggestedIn(BaseModel):
    boards: list[str] = Field(min_length=1, max_length=50)  # "ats:board" from the suggestions


class RunJobOut(BaseModel):
    """One job the last run brought for you: in your list, or left out and why (user, 2026-11-16)."""

    job_id: UUID
    title: str
    company: str | None
    location: str | None
    url: str | None
    in_list: bool
    user_job_id: UUID | None
    status: str | None  # your status, when it's in your list
    score: int | None
    band: str | None
    why: str | None = Field(description="Why it was left out of your list; None when it was kept")


class CompanyJobOut(RunJobOut):
    """One open job at a followed company (user, 2026-11-16)."""

    job_id: UUID | None = Field(
        description="None until the job reaches your BrewMyJob catalog (a few minutes)"
    )
    new: bool  # found by the company's last check
    first_seen_at: datetime


class CompanyJobsOut(BaseModel):
    company: str
    checked_at: datetime | None  # the company's last check
    items: list[CompanyJobOut]
    total: int  # open jobs in India
    new: int  # of them, found by the last check
    in_list: int
    left_out: int


class RunJobsOut(BaseModel):
    ran_at: datetime
    items: list[RunJobOut]
    in_list: int
    left_out: int


class SourceJobsOut(BaseModel):
    """Jobs -> From sources: every open job the sources brought you (user, 2026-11-17)."""

    ran_at: datetime | None = Field(description="When the last run ended; its jobs have new=true")
    items: list[CompanyJobOut]
    total: int
    new: int
    in_list: int
    left_out: int
