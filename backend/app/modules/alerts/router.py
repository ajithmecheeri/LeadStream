"""Google Alerts as a job source (discovery plan decision 10): suggested alerts, and the RSS feeds the user added.

The user creates the alerts on Google (Deliver to: RSS feed) and pastes each feed's link here; BrewMyJob reads the
feeds three times a day. Nothing else is asked of the user.
"""

from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Response, status
from sqlalchemy import delete, func, select

from app.core.deps import User, UserDB
from app.core.errors import AppError, Conflict, NotFound
from app.modules.alerts import feed as feeds
from app.modules.alerts import service
from app.modules.alerts.models import AlertFeed
from app.modules.alerts.query import names_place
from app.modules.alerts.schemas import (
    MAX_ROLES,
    AlertFeedIn,
    AlertFeedOut,
    AlertRolesIn,
    AlertsOut,
    SuggestedAlertOut,
)
from app.modules.alerts.tasks import READ_HOURS_UTC, READ_MINUTE, next_read, queue_read
from app.modules.applications.service import timezone as user_timezone
from app.modules.candidate.models import CandidateProfile
from app.modules.jobs import found
from app.modules.jobs.models import UserJob
from app.modules.matching.models import JobMatch
from app.modules.profiles.models import SearchProfile

router = APIRouter(prefix="/alerts", tags=["alerts"])
MAX_FEEDS = 30
TOP_BANDS = ("strong", "good")


def read_times(tz: str, now: datetime) -> str:
    """The three daily reads on the user's clock: "08:00, 14:00 and 20:00 IST"."""
    zone = ZoneInfo(tz)
    day = now.astimezone(UTC).replace(minute=READ_MINUTE, second=0, microsecond=0)
    times = sorted(day.replace(hour=h).astimezone(zone) for h in READ_HOURS_UTC)
    name = times[0].strftime("%Z")
    if name[:1] in "+-":
        name = f"UTC{name[:3]}"
    clock = sorted(t.strftime("%H:%M") for t in times)
    return f"{', '.join(clock[:-1])} and {clock[-1]} {name}"


async def _top(db, feeds_: list[AlertFeed]) -> dict[UUID, int]:
    ids = {i for f in feeds_ for i in f.last_job_ids or []}
    if not ids:
        return {}
    top = set(
        await db.scalars(
            select(UserJob.id)
            .join(JobMatch, JobMatch.user_job_id == UserJob.id)
            .where(UserJob.id.in_(ids), UserJob.status != "duplicate", JobMatch.band.in_(TOP_BANDS))
        )
    )
    return {f.id: sum(1 for i in f.last_job_ids or [] if i in top) for f in feeds_}


def _out(f: AlertFeed, top: dict[UUID, int]) -> AlertFeedOut:
    return AlertFeedOut(
        id=f.id,
        query=f.query,
        created_at=f.created_at,
        last_read_at=f.last_read_at,
        last_error=f.last_error,
        found=f.last_found,
        added=f.last_added,
        skipped=f.last_skipped,
        top_matches=top.get(f.id, 0),
    )


@router.get("", response_model=AlertsOut)
async def alerts(user: User, db: UserDB):
    """Suggested Google Alerts (one per role and job location) and the feeds you added. The roles are the ones
    you set (up to 5), else your Skill Match profiles' target roles."""
    return await _alerts(db, user.id)


@router.put("/roles", response_model=AlertsOut)
async def set_roles(body: AlertRolesIn, user: User, db: UserDB):
    """Set the roles (up to 5) to get Google Alerts for. An empty list goes back to your target roles. Feeds you
    added stay; create alerts for the new roles from the suggestions."""
    candidate = await db.get(CandidateProfile, user.id, with_for_update=True)
    if candidate is None:
        raise NotFound("Profile")
    candidate.alert_roles = body.roles
    await db.flush()
    return await _alerts(db, user.id)


async def _alerts(db, user_id: UUID) -> AlertsOut:
    profiles = list(
        await db.scalars(select(SearchProfile).where(SearchProfile.active).order_by(SearchProfile.created_at))
    )
    candidate = await db.get(CandidateProfile, user_id)
    own = list(candidate.alert_roles or []) if candidate else []
    roles = (own or found.unique([r for p in profiles for r in p.target_roles], MAX_ROLES))[:MAX_ROLES]
    places = [*(candidate.job_locations if candidate else []), *(x for p in profiles for x in p.locations)]
    rows = list(await db.scalars(select(AlertFeed).order_by(AlertFeed.created_at)))
    top = await _top(db, rows)
    suggestions = []
    cities = found.unique(places, found.MAX_PLACES, found.place_key)
    for role in roles:
        # A role that names its city already ("… ("Bengaluru" OR "Bangalore")") gets one alert, as written.
        where = [None] if names_place(role, cities, found.OTHER_NAME) else (cities or [None])
        for place in where:
            q = service.alert_query(role, place)
            suggestions.append(
                SuggestedAlertOut(
                    role=role,
                    place=place,
                    query=q,
                    create_url=service.create_link(q),
                    added=any(service.same_query(f.query, q) for f in rows),
                )
            )
    now = datetime.now(UTC)
    return AlertsOut(
        roles=roles,
        roles_custom=bool(own),
        suggestions=suggestions,
        feeds=[_out(f, top) for f in rows],
        next_read_at=next_read(now),
        read_times=read_times(await user_timezone(db, user_id), now),
    )


@router.post("", response_model=AlertFeedOut, status_code=status.HTTP_201_CREATED)
async def add_feed(body: AlertFeedIn, user: User, db: UserDB):
    """Add a Google Alerts RSS feed by its link. It is read straight away, then three times a day."""
    try:
        url = feeds.feed_url(body.feed_url)
    except feeds.NotAFeed as e:
        raise AppError(422, "not_a_feed", str(e), [{"field": "feed_url", "message": str(e)}]) from None
    if await db.scalar(select(AlertFeed.id).where(AlertFeed.feed_url == url)):
        raise Conflict("feed_exists", "You've added this feed already")
    if (await db.scalar(select(func.count()).select_from(AlertFeed))) >= MAX_FEEDS:
        raise AppError(
            422, "too_many_feeds", f"Up to {MAX_FEEDS} feeds. Remove one you no longer need first."
        )
    row = AlertFeed(user_id=user.id, feed_url=url, last_job_ids=[])
    db.add(row)
    await db.flush()
    await db.refresh(row)
    await queue_read(user.id, row.id)
    return _out(row, {})


@router.delete("/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_feed(feed_id: UUID, user: User, db: UserDB):
    """Stop reading a feed. Jobs it brought stay in your list. (Delete the alert on Google too.)"""
    result = await db.execute(delete(AlertFeed).where(AlertFeed.id == feed_id))
    if not result.rowcount:
        raise NotFound("Feed")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
