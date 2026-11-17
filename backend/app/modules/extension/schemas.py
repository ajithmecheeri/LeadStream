from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.apply.schemas import EducationEntry, KitDocument, LanguageEntry, WorkEntry


class PairingCodeOut(BaseModel):
    code: str = Field(description="Paste it into the extension. Valid for 10 minutes, once")
    expires_at: datetime


class PairIn(BaseModel):
    code: str = Field(min_length=10, max_length=200)
    name: str | None = Field(
        default=None, max_length=100, description='This browser, e.g. "Chrome on Windows"'
    )


class PairOut(BaseModel):
    token: str = Field(description="This browser's token. Shown once")
    name: str
    email: str


class DeviceOut(BaseModel):
    model_config = {"from_attributes": True}
    id: UUID
    name: str | None
    paired_at: datetime | None
    last_used_at: datetime | None


class FillAnswer(BaseModel):
    key: str
    question: str
    answer: str


class FillJob(BaseModel):
    id: UUID
    title: str
    company: str | None


class FillData(BaseModel):
    """What the extension fills a form with: values by field key (first_name, phone, city, notice_period…), the
    entries for repeated sections, screening answers, and the documents to attach."""

    fields: dict[str, str]
    work_history: list[WorkEntry]
    education: list[EducationEntry]
    languages: list[LanguageEntry]
    answers: list[FillAnswer]
    documents: list[KitDocument]
    job: FillJob | None = Field(description="Your job for this page, when BrewMyJob knows it")
