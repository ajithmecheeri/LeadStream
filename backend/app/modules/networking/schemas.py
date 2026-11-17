from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

Stage = Literal["sent", "accepted", "conversation", "referral", "closed"]


class ImportIn(BaseModel):
    file_name: str = Field(min_length=1, max_length=200, description="Connections.csv or LinkedIn's ZIP")
    content_base64: str = Field(min_length=1, description="The file's bytes, base64-encoded")
    keep_email: bool = Field(False, description="Keep the email addresses the export has (most are blank)")


class ImportOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    file_name: str | None
    total: int
    added: int
    updated: int
    skipped: int
    kept_email: bool
    created_at: datetime


class ConnectionOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    name: str
    profile_url: str | None
    email: str | None
    company: str | None
    position: str | None
    connected_on: date | None


class ConnectionList(BaseModel):
    items: list[ConnectionOut]
    total: int
    limit: int
    offset: int


class NetworkSummary(BaseModel):
    connections: int
    companies: int
    last_import: ImportOut | None
    warm_jobs: int = Field(description="Top matches and applied jobs where you know someone")


class WarmPath(BaseModel):
    user_job_id: UUID
    title: str
    company: str
    score: int | None
    status: str
    people: list[ConnectionOut] = Field(
        description="Up to 5, the most useful first (recruiters, then leaders)"
    )
    total_people: int


class WarmPaths(BaseModel):
    items: list[WarmPath]


class JobPeople(BaseModel):
    company: str | None
    items: list[ConnectionOut]
    imported: bool = Field(description="False until connections are imported")


class SuggestionOut(BaseModel):
    id: UUID
    kind: Literal["warm", "target", "followup"]
    status: Literal["open", "done", "skipped"]
    name: str | None
    title: str | None
    role: str | None = Field(description="Target: who to look for at the company")
    company: str | None
    profile_url: str | None
    search_url: str | None = Field(description="Target: a LinkedIn people search to open yourself")
    user_job_id: UUID | None
    job_title: str | None
    job_score: int | None
    why: str
    note: str
    outreach_id: UUID | None


class Daily(BaseModel):
    date: date
    cap: int
    weekly_sent: int
    weekly_limit: int
    items: list[SuggestionOut]


class Person(BaseModel):
    name: str | None = Field(None, max_length=120)
    title: str | None = Field(None, max_length=200)
    profile_url: str | None = Field(None, max_length=300)


class InviteNoteIn(BaseModel):
    note: str | None = Field(
        None,
        max_length=300,
        description="Your note for invitations to people you don't know yet; empty for ours",
    )


class InviteNoteOut(BaseModel):
    note: str | None = Field(description="Your own note, or null when the built-in one is used")
    example: str = Field(description="The note as a suggestion would show it, for an example job")


class MarkIn(BaseModel):
    action: Literal["sent", "skipped"]
    person: Person | None = Field(None, description="Target: who you found and wrote to")
    note: str | None = Field(None, max_length=2000, description="The note as you sent it, if you changed it")


class OutreachIn(BaseModel):
    person_name: str = Field(min_length=1, max_length=120)
    title: str | None = Field(None, max_length=200)
    company: str | None = Field(None, max_length=200)
    profile_url: str | None = Field(None, max_length=300)
    user_job_id: UUID | None = None
    note: str | None = Field(None, max_length=2000)

    @field_validator("person_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Name the person")
        return v


class OutreachPatch(BaseModel):
    version: int = Field(description="The version you last read; a stale version returns 409")
    stage: Stage | None = None
    note: str | None = Field(None, max_length=2000)


class OutreachEventOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    kind: Literal["sent", "stage", "followed_up", "note"]
    stage: str | None
    note: str | None
    at: datetime


class OutreachOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    kind: Literal["warm", "target", "manual"]
    person_name: str | None
    title: str | None
    company: str | None
    profile_url: str | None
    user_job_id: UUID | None
    job_title: str | None = None
    note: str | None
    stage: Stage
    stage_at: datetime
    followed_up_at: datetime | None
    version: int
    created_at: datetime


class OutreachDetail(OutreachOut):
    events: list[OutreachEventOut]


class OutreachList(BaseModel):
    items: list[OutreachOut]
    counts: dict[str, int]


class PeopleSearch(BaseModel):
    kind: Literal["hr", "leaders", "hiring_manager"]
    label: str
    url: str = Field(description="A LinkedIn people search the user opens in their own browser")


class AppliedCompany(BaseModel):
    user_job_id: UUID
    company: str
    job_title: str
    applied_on: date
    status: str
    searches: list[PeopleSearch]
    note: str = Field(description="An invitation note after applying (at most 300 characters)")
    people: list[ConnectionOut] = Field(
        description="Up to 3 people you know there, recruiters and leaders first"
    )
    total_people: int
    contacted: int = Field(description="Outreach you recorded for this job")


class AppliedCompanies(BaseModel):
    days: int
    items: list[AppliedCompany]
