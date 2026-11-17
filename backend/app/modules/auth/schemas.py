from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, ValidationInfo, field_validator

from app.modules.access.schemas import AccessOut
from app.modules.candidate.locations import check_locations
from app.modules.notifications.whatsapp import normalise_number


def _name_part(v: str | None) -> str | None:
    return " ".join(v.split()) or None if v is not None else None


class NameParts(BaseModel):
    first_name: str = Field(min_length=1, max_length=60)
    middle_name: str | None = Field(None, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)

    @field_validator("first_name", "last_name")
    @classmethod
    def _required(cls, v: str, info: ValidationInfo) -> str:
        v = _name_part(v) or ""
        if not v:
            raise ValueError(f"{'First' if info.field_name == 'first_name' else 'Last'} name is required")
        return v

    @field_validator("middle_name")
    @classmethod
    def _optional(cls, v: str | None) -> str | None:
        return _name_part(v)


class SignupIn(NameParts):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    password_confirm: str = Field(max_length=200, description="The password again; must match")
    accept_terms: bool = Field(description="Consent to the privacy notice; must be true")
    job_locations: list[str] = Field(
        min_length=1, max_length=10, description="Where you want to work: cities, or Remote (at least one)"
    )
    whatsapp_number: str | None = Field(
        None,
        max_length=20,
        description="Optional: for WhatsApp alerts on strong matches; verified in Settings",
    )
    invite: str | None = Field(None, max_length=200, description="The token of an invite link, if any")

    @field_validator("whatsapp_number")
    @classmethod
    def _number(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        number = normalise_number(v)
        if number is None:
            raise ValueError("Enter a mobile number with its country code, e.g. +91 98765 43210")
        return number

    @field_validator("password_confirm")
    @classmethod
    def _same(cls, v: str, info: ValidationInfo) -> str:
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("The passwords don't match")
        return v

    @field_validator("accept_terms")
    @classmethod
    def _must_accept(cls, v: bool) -> bool:
        if not v:
            raise ValueError("You need to accept the privacy notice to create an account")
        return v

    @field_validator("job_locations")
    @classmethod
    def _places(cls, v: list[str]) -> list[str]:
        return check_locations(v)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class RefreshIn(BaseModel):
    """Mobile clients send the refresh token in the body; the web uses the HttpOnly cookie."""

    refresh_token: str | None = None


class MeOut(BaseModel):
    id: UUID
    email: str
    name: str = Field(description="Display name: first, middle and last name together")
    first_name: str
    middle_name: str | None
    last_name: str | None
    role: str = Field(description="job_seeker | admin | super_admin")
    access: AccessOut
    timezone: str
    forwarding_address: str
    created_at: datetime


class MePatch(BaseModel):
    """Change any of these; send middle_name null (or "") to remove it."""

    first_name: str | None = Field(None, max_length=60)
    middle_name: str | None = Field(None, max_length=60)
    last_name: str | None = Field(None, max_length=60)
    timezone: str | None = Field(None, min_length=3, max_length=64)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str | None = Field(None, description="Only returned to mobile clients (X-Client: mobile)")
    user: MeOut
