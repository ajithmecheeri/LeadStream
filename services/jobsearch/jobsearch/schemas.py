from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

System = Literal[
    "greenhouse", "lever", "ashby", "smartrecruiters", "workday", "oracle", "eightfold", "careers_page"
]


class RunOut(BaseModel):
    id: UUID
    connector: str
    board_id: UUID | None
    search_area_id: UUID | None
    started_at: datetime
    finished_at: datetime | None
    found: int
    new: int
    updated: int
    reposted: int
    closed: int
    pending: int  # Workday postings whose details are still to read
    error: str | None


class EmployerIn(BaseModel):
    """Register by careers link (`url`), or by `system` + `board`. `id` keeps an existing id (the app's import
    of its old company feeds)."""

    id: UUID | None = None
    name: str | None = Field(None, max_length=120)
    url: str | None = Field(None, max_length=500)
    system: System | None = None
    board: str | None = Field(None, max_length=200)

    @model_validator(mode="after")
    def _one_way(self):
        if not self.url and not (self.system and self.board):
            raise ValueError("Give a careers link, or a hiring system and board")
        return self


class EmployerOut(BaseModel):
    id: UUID
    name: str
    system: System
    board: str
    board_url: str
    last_checked_at: datetime | None
    last_error: str | None
    jobs_total: int | None
    jobs_in_scope: int | None  # jobs in the service's country (India)
    last_run: RunOut | None


class LookupIn(BaseModel):
    query: str = Field(min_length=2, max_length=300)


class FoundOut(BaseModel):
    system: System
    board: str
    board_url: str
    in_scope: int
    total: int
    sample: list[str]


class SuggestedOut(BaseModel):
    name: str
    system: System
    board: str
    board_url: str


class SearchAreaIn(BaseModel):
    location: str = Field(min_length=1, max_length=80)
    role_family: str = Field(min_length=1, max_length=40)
    titles: list[str] = Field(default_factory=list, max_length=20)


class DemandIn(BaseModel):
    areas: list[SearchAreaIn] = Field(max_length=500)


class DemandOut(BaseModel):
    active: int


class ListingSourceOut(BaseModel):
    source: str
    source_job_id: str
    url: str | None
    apply_url: str | None


class ListingOut(BaseModel):
    listing_id: UUID
    employer_id: UUID | None
    company: str | None
    title: str
    location: str | None
    work_model: str | None
    experience: str | None
    salary: str | None
    description: str | None
    skills: list[str]
    details: dict
    posted_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    closed_at: datetime | None
    status: Literal["pending", "active", "closed"]
    sources: list[ListingSourceOut]
    requisition_id: str | None
    content_hash: str
    version: int


class VersionOut(BaseModel):
    version: int
    replaced_at: datetime
    snapshot: dict


class ListingDetailOut(ListingOut):
    versions: list[VersionOut]


class EmployerListingsOut(BaseModel):
    """An employer's open listings, newest first, without descriptions. A listing whose `first_seen_at` is at or
    after `last_run.started_at` was found by the board's last run."""

    employer_id: UUID
    last_run: RunOut | None
    listings: list[ListingOut]


class EventOut(BaseModel):
    event_id: int  # the cursor
    type: Literal["NEW", "UPDATED", "REPOSTED", "CLOSED"]
    occurred_at: datetime
    listing: ListingOut


class EventsOut(BaseModel):
    events: list[EventOut]
    next_cursor: int  # pass as `after` next time (unchanged when there was nothing new)


class SourceOut(BaseModel):
    connector: str
    configured: bool
    boards: int  # employer boards on this system (0 for job APIs)
    last_run_at: datetime | None
    runs_24h: int
    failures_24h: int
    last_error: str | None
