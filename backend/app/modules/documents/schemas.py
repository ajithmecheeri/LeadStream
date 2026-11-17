from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

MAX_RESUMES = 4  # one primary and up to three variations
MAX_COVER_LETTERS = 5


class DocumentIn(BaseModel):
    """An uploaded file (file_name + content_base64) or pasted text: exactly one of the two."""

    label: str | None = Field(None, max_length=60, description="Defaults to the file name")
    file_name: str | None = Field(None, max_length=200)
    content_base64: str | None = Field(None, description="The file's bytes, base64-encoded")
    text: str | None = Field(None, max_length=50_000, description="Pasted text instead of a file")

    @model_validator(mode="after")
    def _one_source(self):
        has_file = bool(self.content_base64)
        if has_file == bool(self.text and self.text.strip()):
            raise ValueError("send either a file (file_name and content_base64) or text, not both")
        if has_file and not self.file_name:
            raise ValueError("file_name is required with a file")
        if self.label is not None:
            self.label = " ".join(self.label.split()) or None
        return self


class ResumeIn(DocumentIn):
    focus_tags: list[str] = Field(default_factory=list, max_length=10)


class FileInfo(BaseModel):
    file_name: str | None
    file_kind: str | None
    file_size: int | None
    characters: int


class ResumeOut(FileInfo):
    id: UUID
    label: str
    focus_tags: list[str]
    search_profile_id: UUID | None
    is_primary: bool
    source: str
    version: int
    created_at: datetime
    updated_at: datetime


class ResumeDetail(ResumeOut):
    text: str


class ResumeList(BaseModel):
    items: list[ResumeOut]
    limit: int = MAX_RESUMES


class ResumePatch(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=60)
    focus_tags: list[str] | None = Field(None, max_length=10)
    search_profile_id: UUID | None = Field(None, description="Focus search profile; send null to clear")
    version: int = Field(description="The version you last read; a stale version returns 409")


class CoverLetterOut(FileInfo):
    id: UUID
    label: str
    is_default: bool
    version: int
    created_at: datetime
    updated_at: datetime


class CoverLetterDetail(CoverLetterOut):
    text: str


class CoverLetterList(BaseModel):
    items: list[CoverLetterOut]
    limit: int = MAX_COVER_LETTERS


class CoverLetterPatch(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=60)
    text: str | None = Field(None, min_length=100, max_length=50_000)
    version: int = Field(description="The version you last read; a stale version returns 409")
