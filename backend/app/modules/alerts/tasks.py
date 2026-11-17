"""Worker tasks for Google Alerts feeds: every feed at 08:00, 14:00 and 20:00 IST (02:30, 08:30, 14:30 UTC), and one
feed as soon as it is added."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.worker import app, defer
from app.modules.alerts import service

log = logging.getLogger("fitfirst.alerts")

READ_FEED = "alerts.read_feed"
READ_HOURS_UTC = (2, 8, 14)  # at :30 → 08:00, 14:00, 20:00 IST
READ_MINUTE = 30


def next_read(now: datetime) -> datetime:
    now = now.astimezone(UTC)
    for day in (0, 1):
        for hour in READ_HOURS_UTC:
            at = (now + timedelta(days=day)).replace(hour=hour, minute=READ_MINUTE, second=0, microsecond=0)
            if at > now:
                return at
    raise AssertionError("unreachable")


async def queue_read(user_id: UUID, feed_id: UUID) -> None:
    await defer(READ_FEED, schedule_in_seconds=2, user_id=str(user_id), feed_id=str(feed_id))


@app.task(name=READ_FEED, queue="sources")
async def read_feed(user_id: str, feed_id: str) -> None:
    await service.read(UUID(user_id), UUID(feed_id))


@app.periodic(cron="30 2,8,14 * * *", periodic_id="google-alerts")
@app.task(name="alerts.read_all", queue="sources", queueing_lock="alerts.read_all")
async def read_all(timestamp: int) -> None:
    await service.read_all()
