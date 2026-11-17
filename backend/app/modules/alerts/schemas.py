from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.modules.alerts.query import BadQuery, google_terms


class SuggestedAlertOut(BaseModel):
    role: str
    place: str | None
    query: str  # what to paste in Google Alerts (LinkedIn, Naukri and Foundit job pages in one alert)
    create_url: str  # Google Alerts with the query filled in
    added: bool  # one of your feeds already has this query


class AlertFeedOut(BaseModel):
    id: UUID
    query: str | None  # the alert's search, as Google names the feed
    created_at: datetime
    last_read_at: datetime | None
    last_error: str | None
    found: int  # job pages in the feed at the last read
    added: int  # of them, new to you
    skipped: int  # links to other sites (skipped)
    top_matches: int  # of the jobs it brought, in your Top matches now


MAX_ROLES = 5


class AlertsOut(BaseModel):
    roles: list[str]  # the roles alerts are suggested for (yours, else your target roles), at most 5
    roles_custom: bool  # True: you set them; False: taken from your Skill Match profiles
    suggestions: list[SuggestedAlertOut]
    feeds: list[AlertFeedOut]
    next_read_at: datetime
    read_times: str  # "08:00, 14:00 and 20:00 IST" on the user's clock


class AlertRolesIn(BaseModel):
    """Up to 5 roles to get Google Alerts for. An empty list goes back to your target roles."""

    roles: list[str] = Field(max_length=MAX_ROLES)

    @field_validator("roles")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        """Saved in Google's syntax: '(A OR B) (Bengaluru OR Bangalore)' → '("A" OR "B") ("Bengaluru" OR …)'."""
        out: dict[str, str] = {}
        for r in v:
            if not r.strip(' "()|'):
                continue
            if len(r.strip()) < 2:
                raise ValueError("Each role is at least 2 characters")
            try:
                q = google_terms(r)
            except BadQuery as e:
                raise ValueError(f"{r.strip()}: {e}") from None
            out.setdefault(q.lower(), q)
        return list(out.values())


class AlertFeedIn(BaseModel):
    feed_url: str = Field(min_length=10, max_length=300)
