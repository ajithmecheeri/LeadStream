"""Worker tasks for job sources, now served by the Job Search Service (docs/plan-jobsearch-build.md):

  - every 5 minutes: send the aggregated demand when it changed, then pull the service's event feed;
  - on request: check one user's followed employers now ("Check now", following a company), then pull.

The service itself reads every employer board every 3 hours and the job APIs every 6 hours (UTC).
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from procrastinate.exceptions import AlreadyEnqueued

from app.core.worker import app, defer
from app.modules.sources import client, sync

log = logging.getLogger("fitfirst.sources")

REFRESH_USER = "sources.refresh_user"
PULL = "sources.pull"
CATCH_UP_USER = "sources.catch_up_user"
BOARD_HOURS = 3  # the service reads every board every 3 hours, on the hour (UTC)


def next_check(now: datetime) -> datetime:
    """When the service's next scheduled read of the boards starts."""
    now = now.astimezone(UTC)
    start = now.replace(minute=0, second=0, microsecond=0, hour=now.hour - now.hour % BOARD_HOURS)
    return start + timedelta(hours=BOARD_HOURS)


def check_times(tz: str, now: datetime) -> str:
    """The schedule on the user's clock: "every 3 hours (next at 09:30 IST)"."""
    nxt = next_check(now).astimezone(ZoneInfo(tz))
    name = nxt.strftime("%Z")
    if name[:1] in "+-":  # a zone without a short name ("+04", "+0545"): say it as an offset from UTC
        name = f"UTC{name[:3]}" + (f":{name[3:]}" if name[3:].strip("0") else "")
    return f"every {BOARD_HOURS} hours (next at {nxt.strftime('%H:%M')} {name})"


async def queue_refresh(user_id: UUID, employer_ids: list[UUID] | None = None) -> None:
    """Check the user's followed employers in the background. A full check is queued at most once at a time."""
    lock = None if employer_ids else f"sources:{user_id}"
    try:
        await defer(
            REFRESH_USER,
            queueing_lock=lock,
            schedule_in_seconds=3,  # lets the request that asked for it commit first
            user_id=str(user_id),
            employer_ids=[str(e) for e in employer_ids] if employer_ids else None,
        )
    except AlreadyEnqueued:
        pass


@app.task(name=REFRESH_USER, queue="sources")
async def refresh_user_task(user_id: str, employer_ids: list[str] | None = None) -> None:
    try:
        async with client.connect() as js:
            await sync.check_user(
                js, UUID(user_id), [UUID(e) for e in employer_ids] if employer_ids else None
            )
    except client.Unavailable as e:
        log.warning("job search service unavailable for a check: %s", e)
        await sync.note_error(f"Job search service unavailable ({e})")


async def queue_catch_up(user_id: UUID) -> None:
    """Bring every shared company's open jobs to a user whose first Skill Match profile was just made."""
    try:
        await defer(
            CATCH_UP_USER, queueing_lock=f"catch-up:{user_id}", schedule_in_seconds=5, user_id=str(user_id)
        )
    except AlreadyEnqueued:
        pass


@app.task(name=CATCH_UP_USER, queue="sources")
async def catch_up_user_task(user_id: str) -> None:
    try:
        async with client.connect() as js:
            await sync.catch_up_all(js, UUID(user_id))
    except client.Unavailable as e:
        log.warning("job search service unavailable for a catch-up: %s", e)


@app.periodic(cron="*/5 * * * *", periodic_id="jobsearch-pull")
@app.task(name=PULL, queue="sources", queueing_lock=PULL)
async def pull(timestamp: int) -> None:
    try:
        async with client.connect() as js:
            await sync.push_demand(js)
            await sync.pull(js)
    except client.Unavailable as e:
        log.warning("job search service unavailable: %s", e)
        await sync.note_error(f"Job search service unavailable ({e})")
