"""POC (user, 2026-11-17): "Add to BrewMyJob" on Google's search results, from the browser extension.

The user searches on Google in their own browser; the extension puts a button next to each LinkedIn, Naukri or
Foundit job result, and on the user's click sends what Google shows (link, title, snippet). Only those fields are
used, as for Google Alerts: the link is read for the portal's job id and the portal page is never opened.

To remove the POC: delete this file, its line in app/main.py, tests/test_extension_google.py,
apps/extension/src/google.js, the "content_scripts" entry in apps/extension/manifest.json and the "google-result"
message in apps/extension/src/background.js (docs/plan-m14.md, "Add from Google results").
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.errors import AppError
from app.modules.alerts import feed as feeds
from app.modules.catalog.service import upsert_cards
from app.modules.extension.router import Extension
from app.modules.jobs.linking import link_cards
from app.modules.jobs.models import UserJob
from app.modules.matching.service import queue_scoring

router = APIRouter(prefix="/extension", tags=["extension"])


class GoogleResultIn(BaseModel):
    url: str = Field(
        min_length=10, max_length=2000, description="The result's link (Google's redirect is fine)"
    )
    title: str = Field(min_length=2, max_length=500, description="The result's title as Google shows it")
    snippet: str | None = Field(default=None, max_length=2000)


class GoogleResultOut(BaseModel):
    user_job_id: str
    title: str
    company: str | None
    already: bool  # it was in the user's list before


@router.post("/google-result", response_model=GoogleResultOut, status_code=201)
async def add_google_result(body: GoogleResultIn, ext: Extension):
    """Add a job from a Google search result the user clicked "Add to BrewMyJob" on. Unverified and scored from the
    title and snippet, like a Google Alerts job."""
    link = feeds.target(body.url)
    entry = feeds.Entry(link=link, title=body.title, snippet=body.snippet, published=None)
    got = feeds.cards(feeds.Feed(query=None, entries=[entry]))
    if not got.cards:
        raise AppError(
            422,
            "not_a_job_link",
            "Only LinkedIn, Naukri and Foundit job pages can be added from Google",
            [{"field": "url", "message": "Not a job page"}],
        )
    [card] = got.cards
    card.details["Found by"] = "Google search (extension)"
    db = ext.db
    [match] = await upsert_cards(db, [card], verified=False)
    added = await link_cards(db, ext.user_id, [card], [match])
    uj = await db.scalar(select(UserJob).where(UserJob.job_id == match.job_id))
    if uj is None:
        raise AppError(500, "not_added", "The job couldn't be added")
    if uj.status == "duplicate" and uj.duplicate_of:
        uj = await db.get(UserJob, uj.duplicate_of) or uj
    if added:
        # A new job waits in Jobs → From Google until the user keeps or ignores it (user, 2026-11-17).
        uj.status = "review"
    await db.flush()
    await queue_scoring(ext.user_id, "job added from google", user_job_ids=[uj.id])
    return GoogleResultOut(user_job_id=str(uj.id), title=card.title, company=card.company, already=not added)
