from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class AccessOut(BaseModel):
    active: bool
    until: datetime | None = Field(description="When the plan or coupon period ends (None for admins)")
    why: Literal["admin", "free", "plan", "none"]


class PlanOut(BaseModel):
    id: str
    months: int
    price_inr: int
    label: str


class PlansOut(BaseModel):
    plans: list[PlanOut]
    access: AccessOut
    payments_open: bool = Field(description="False until the payment gateway is built (backlog)")


class InviteIn(BaseModel):
    email: EmailStr
    role: Literal["job_seeker", "admin"] = "job_seeker"
    free_months: Literal[0, 1, 3] = Field(0, description="A coupon: 1 or 3 months free (job seekers only)")


class InviteOut(BaseModel):
    id: UUID
    email: str
    role: str
    free_months: int
    state: Literal["open", "accepted", "revoked", "expired"]
    created_at: datetime
    expires_at: datetime
    accepted_at: datetime | None


class InviteMade(InviteOut):
    link: str = Field(description="Send this link to the person; it is shown once")


class InviteView(BaseModel):
    """What the invite's link shows before signing up or in."""

    email: str
    role: str
    free_months: int
    has_account: bool


class AcceptIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
