from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Reason = Literal[
    "field", "too_junior", "too_senior", "location", "company", "salary", "applied_elsewhere", "other"
]


class NotForMeIn(BaseModel):
    reason: Reason
    note: str | None = Field(default=None, max_length=500, description="Optional, in the user's words")
    version: int = Field(description="The job's version, as for a status change")


class LearnedOut(BaseModel):
    model_config = {"from_attributes": True}
    id: UUID
    kind: Literal["company", "location", "field", "level_min", "level_max"]
    label: str = Field(description='How it reads on Profile: "Jobs at Okta", "Roles below director level"')
    created_at: datetime
