from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

AppStatus = Literal["applied", "interviewing", "offer", "accepted", "rejected", "withdrawn", "no_response"]


class AppJob(BaseModel):
    user_job_id: UUID
    title: str
    company: str | None
    location: str | None
    score: int | None


class ApplicationOut(BaseModel):
    id: UUID
    status: AppStatus
    applied_on: date
    follow_up_on: date | None
    follow_up_due: bool = Field(description="The follow-up date is today or past and the application is open")
    resume_id: UUID | None
    resume_label: str | None
    cover_letter_id: UUID | None
    cover_letter_label: str | None
    version: int
    updated_at: datetime
    job: AppJob


class EventOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    kind: Literal["applied", "status", "note", "follow_up"]
    from_status: str | None
    to_status: str | None
    note: str | None
    at: datetime


class ApplicationDetail(ApplicationOut):
    events: list[EventOut]


class ApplicationList(BaseModel):
    items: list[ApplicationOut]
    total: int
    limit: int
    offset: int
    counts: dict[str, int] = Field(description="Applications per status, ignoring the status filter")
    follow_ups_due: int


class ApplicationPatch(BaseModel):
    """Send only what changes; `follow_up_on: null` clears the follow-up date."""

    version: int = Field(description="The version you last read; a stale version returns 409")
    status: AppStatus | None = None
    applied_on: date | None = None
    follow_up_on: date | None = None
    resume_id: UUID | None = None
    cover_letter_id: UUID | None = None


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Write a note")
        return v


def _clean(v: str | None) -> str | None:
    return " ".join(v.split()) or None if v is not None else None


class ContactIn(BaseModel):
    name: str | None = Field(None, max_length=120)
    role: str | None = Field(None, max_length=120, description="e.g. Recruiter, Hiring manager")
    linkedin_url: str | None = Field(None, max_length=300)
    email: EmailStr | None = None
    note: str | None = Field(None, max_length=1000)

    @field_validator("name", "role", "note", mode="before")
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        return _clean(v) if isinstance(v, str) else v

    @field_validator("email", mode="before")
    @classmethod
    def _blank_email(cls, v: str | None) -> str | None:
        return (v.strip() or None) if isinstance(v, str) else v

    @field_validator("linkedin_url", mode="before")
    @classmethod
    def _linkedin(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if not v:
            return None
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        host = v.split("://", 1)[1].split("/", 1)[0].lower()
        if host != "linkedin.com" and not host.endswith(".linkedin.com"):
            raise ValueError("Paste a LinkedIn profile link (linkedin.com/in/…)")
        return v

    @model_validator(mode="after")
    def _something(self):
        if not (self.name or self.linkedin_url or self.email):
            raise ValueError("Add a name, a LinkedIn profile link or an email")
        return self


class ContactPatch(ContactIn):
    version: int = Field(description="The version you last read; a stale version returns 409")


class ContactOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    name: str | None
    role: str | None
    linkedin_url: str | None
    email: str | None
    note: str | None
    version: int
    created_at: datetime


class FoundContact(BaseModel):
    kind: Literal["email", "linkedin"]
    value: str  # the address, or the profile's name part
    url: str  # mailto:… or the LinkedIn profile link
    context: str | None = Field(description="The line of the description it appeared in")


class ContactList(BaseModel):
    from_email: str | None = Field(description="The recruiter the alert email named, when it named one")
    items: list[ContactOut]
    found: list[FoundContact] = Field(
        default_factory=list, description="Emails and LinkedIn profiles written in the job description"
    )
