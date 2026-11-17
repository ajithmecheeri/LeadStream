"""Reading a user's Google Alerts feeds into their jobs (discovery plan decision 10).

A feed is fetched outside any transaction, only from www.google.com/alerts/feeds/… (no redirects followed). Its job
links become unverified catalog cards, linked to the user and scored; the read is noted on the feed and as a run
line (`source_runs`, source `google_alert`).
"""

import logging
from datetime import UTC, datetime
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy import select

from app.core.db import sessionmaker, user_scope
from app.modules.alerts import feed as feeds
from app.modules.alerts.models import AlertFeed, SourceRun
from app.modules.alerts.query import BadQuery, google_terms
from app.modules.catalog.service import upsert_cards
from app.modules.jobs import found
from app.modules.jobs.linking import link_cards
from app.modules.jobs.models import UserJob
from app.modules.matching.service import queue_scoring
from app.modules.users.models import User

log = logging.getLogger("fitfirst.alerts")

TIMEOUT = 20.0
SITES = " OR ".join(f"site:{path}" for _, path in found.PORTALS.values())


# --- Suggested alerts ----------------------------------------------------------------------------------------


def alert_query(role: str, place: str | None) -> str:
    """One alert for LinkedIn, Naukri and Foundit job pages:
    '"VP Engineering" ("Bengaluru" OR "Bangalore") (site:…)'. The role may be an expression of its own
    ('("Technology Director" OR "Engineering Director")', alerts/query.py)."""
    try:
        q = google_terms(role)
    except BadQuery:
        q = f'"{role.replace(chr(34), "")}"'
    if place:
        q += f" {found.place_term(place)}"
    return f"{q} ({SITES})"


def create_link(query: str) -> str:
    return f"https://www.google.com/alerts?q={quote(query)}"


def same_query(a: str | None, b: str | None) -> bool:
    return bool(a and b) and " ".join(a.lower().split()) == " ".join(b.lower().split())  # type: ignore[union-attr]


# --- Reading -----------------------------------------------------------------------------------------------


class FetchError(Exception):
    pass


async def fetch(url: str) -> bytes:
    """The feed's content. Only Google's feed links reach here (feeds.feed_url)."""
    async with httpx.AsyncClient(
        timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": "BrewMyJob feed reader"}
    ) as http:
        r = await http.get(feeds.feed_url(url))
    if r.status_code == 404:
        raise FetchError(
            "Google says this feed no longer exists: the alert was deleted or no longer goes to RSS"
        )
    if r.status_code != 200:
        raise FetchError(f"Google answered {r.status_code}; it will be tried again at the next read")
    return r.content


async def read(user_id: UUID, feed_id: UUID) -> int:
    """Read one feed now. Returns the number of jobs new to the user."""
    async with user_scope(user_id) as db:
        row = await db.get(AlertFeed, feed_id)
        if row is None:
            return 0
        url = row.feed_url
    try:
        parsed = feeds.parse(await fetch(url))
    except (FetchError, feeds.NotAFeed, httpx.HTTPError) as e:
        message = str(e) or "The feed couldn't be read; it will be tried again at the next read"
        if isinstance(e, httpx.HTTPError):
            message = "Google couldn't be reached; it will be tried again at the next read"
        async with user_scope(user_id) as db:
            row = await db.get(AlertFeed, feed_id)
            if row is not None:
                row.last_read_at, row.last_error = datetime.now(UTC), message[:500]
                db.add(SourceRun(user_id=user_id, source="google_alert", error=message[:500]))
        log.info("google alert feed %s: %s", feed_id, message)
        return 0
    got = feeds.cards(parsed)
    added: list[UUID] = []
    async with user_scope(user_id) as db:
        row = await db.get(AlertFeed, feed_id)
        if row is None:
            return 0
        ids: list[UUID] = []
        if got.cards:
            # Google's result, not the portal: unverified, like a job added by hand (never changes a known job).
            matches = await upsert_cards(db, got.cards, verified=False)
            added = await link_cards(db, user_id, got.cards, matches)
            ids = list(
                await db.scalars(select(UserJob.id).where(UserJob.job_id.in_([m.job_id for m in matches])))
            )
        row.query = parsed.query or row.query
        row.last_read_at, row.last_error = datetime.now(UTC), None
        row.last_found, row.last_added, row.last_skipped = len(got.cards), len(added), got.other_links
        row.last_job_ids = ids
        db.add(
            SourceRun(
                user_id=user_id,
                source="google_alert",
                found=len(got.cards),
                added=len(added),
                skipped=got.other_links,
            )
        )
    if ids:
        await queue_scoring(user_id, "jobs from google alerts", user_job_ids=ids, delay=0)
    return len(added)


async def read_all() -> int:
    """Every active user's feeds (the 08:00, 14:00 and 20:00 IST reads)."""
    async with sessionmaker()() as db:
        users = list(await db.scalars(select(User.id).where(User.status == "active")))
    total = 0
    for uid in users:
        async with user_scope(uid) as db:
            ids = list(await db.scalars(select(AlertFeed.id).order_by(AlertFeed.created_at)))
        for fid in ids:
            total += await read(uid, fid)
    if total:
        log.info("google alerts: %d new jobs for users", total)
    return total
