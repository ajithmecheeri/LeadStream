from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ReadinessStatus = Literal["ready", "needs_input", "manual_only"]


class BlockerOut(BaseModel):
    key: str = Field(description="Stable id: question:<key>, description, cover_letter or gap:<factor>")
    kind: Literal["question", "description", "cover_letter", "gap"]
    title: str
    detail: str
    question: str | None = Field(None, description="For questions: what the answer bank stores it as")


class ReadinessOut(BaseModel):
    status: ReadinessStatus
    blockers: list[BlockerOut]


class ReadinessSummary(BaseModel):
    status: ReadinessStatus
    blockers: int


class ResolveIn(BaseModel):
    answer: str | None = Field(
        None, max_length=2000, description="For a question: your answer (saved to the bank)"
    )

    @field_validator("answer")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


class AnswerOut(BaseModel):
    key: str
    question: str
    answer: str | None
    source: Literal["you", "profile"] | None = Field(
        description="you: saved in the bank; profile: from your profile"
    )
    standard: bool
    required: bool
    updated_at: datetime | None
    stale: bool = Field(description="Saved more than 30 days ago: worth checking it's still right")
    choices: list[str] = Field(default_factory=list, description="The usual answers, offered as quick picks")
    version: int | None


class AnswerList(BaseModel):
    items: list[AnswerOut]


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)
    version: int | None = Field(None, description="The version you last read, when updating a saved answer")

    @field_validator("answer")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Write an answer")
        return v


class CustomAnswerIn(AnswerIn):
    question: str = Field(min_length=5, max_length=300)

    @field_validator("question")
    @classmethod
    def _q(cls, v: str) -> str:
        return " ".join(v.split())
