from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

Month = Field(default=None, pattern=r"^(19|20)\d\d-(0[1-9]|1[0-2])$", description="YYYY-MM")


class WorkEntry(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    start: str | None = Month
    end: str | None = Month
    current: bool = False
    description: str | None = Field(default=None, max_length=4000)


class EducationEntry(BaseModel):
    school: str = Field(min_length=1, max_length=200)
    degree: str | None = Field(default=None, max_length=200)
    field: str | None = Field(default=None, max_length=200)
    start_year: int | None = Field(default=None, ge=1950, le=2100)
    end_year: int | None = Field(default=None, ge=1950, le=2100)


class LanguageEntry(BaseModel):
    language: str = Field(min_length=1, max_length=60)
    proficiency: Literal["basic", "conversational", "fluent", "native"] | None = None


class ApplyProfileFields(BaseModel):
    phone: str | None = Field(default=None, max_length=40)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=100)
    websites: list[HttpUrl] = Field(default_factory=list, max_length=5)
    languages: list[LanguageEntry] = Field(default_factory=list, max_length=10)
    work_history: list[WorkEntry] = Field(
        default_factory=list, max_length=30, description="Most recent first"
    )
    education: list[EducationEntry] = Field(default_factory=list, max_length=10)


class ApplyProfileIn(ApplyProfileFields):
    version: int = Field(description="0 for the first save")


class ApplyProfileOut(ApplyProfileFields):
    websites: list[str] = Field(default_factory=list)  # type: ignore[assignment]
    version: int = Field(description="0 until the first save")
    updated_at: datetime | None


class ApplyDraft(BaseModel):
    """Read from a resume, for the user to review. Nothing is saved until they PUT /apply-profile."""

    phone: str | None = None
    city: str | None = None
    work_history: list[WorkEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)


class FromResumeIn(BaseModel):
    resume_id: UUID


class KitField(BaseModel):
    key: str = Field(description='Stable: "phone", "work.0.title", "answer:notice_period"')
    label: str
    value: str


class KitSection(BaseModel):
    title: str
    fields: list[KitField]


class KitDocument(BaseModel):
    id: UUID
    label: str
    kind: Literal["resume", "cover_letter"]


class ApplyKitOut(BaseModel):
    """Everything an application form asks for, in Workday's order, to copy field by field."""

    sections: list[KitSection]
    documents: list[KitDocument] = Field(description="The suggested resume and cover letter for this job")
    missing: list[str] = Field(description="What the forms usually ask for that BrewMyJob doesn't have yet")
