"""Worker tasks for received emails: parse each one, and housekeeping (rescue stuck messages, purge raw
emails after the retention period)."""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import procrastinate
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import sessionmaker, user_scope
from app.core.worker import app
from app.modules.applications import service as applications
from app.modules.catalog.parsers import parse_email
from app.modules.catalog.service import upsert_cards
from app.modules.ingestion.models import InboundMessage, InboundRaw
from app.modules.ingestion.service import PARSE_ALERT, forward_senders, queue_parse
from app.modules.jobs.linking import link_cards
from app.modules.jobs.models import UserJob
from app.modules.matching.service import queue_scoring
from app.modules.users.models import User

log = logging.getLogger("fitfirst.ingestion")


async def process_message(inbound_message_id: UUID, user_id: UUID) -> str:
    """Parse one received email, store its jobs in the catalog and link them to the user. Safe to repeat.

    Returns the message's new status: 'parsed', or 'unparsed' when no parser recognises the email or it
    holds no jobs.
    """
    async with user_scope(user_id) as db:
        msg = await db.get(InboundMessage, inbound_message_id, with_for_update=True)
        raw = await db.get(InboundRaw, inbound_message_id)
        if msg is None:
            log.warning("inbound message %s is gone (account deleted?)", inbound_message_id)
            return "missing"
        if raw is None:
            # Purged before it was parsed: nothing left to read, and the sweep must not keep retrying.
            msg.status, msg.processed_at = "failed", datetime.now(UTC)
            msg.error = "The email was deleted (retention period) before it could be read"
            return msg.status

        forwards_from = await forward_senders(db)
        result = parse_email(raw.body, forwards_from)
        msg.processed_at, msg.error = datetime.now(UTC), None
        if result is None or not result.cards:
            msg.status, msg.cards_found = "unparsed", 0
            msg.parser = result.parser if result else None
            msg.error = "; ".join(result.warnings) if result and result.warnings else None
            return msg.status

        # A hand forward lost the portal's DKIM signature: its jobs go into the catalog unverified.
        matches = await upsert_cards(db, result.cards, verified=msg.sender not in forwards_from)
        await link_cards(db, user_id, result.cards, matches, inbound_message_id)
        await _record_applied(db, result.applied, matches)
        msg.status, msg.cards_found = "parsed", len(result.cards)
        msg.parser, msg.alert_name = result.parser, result.alert_name
        msg.error = "; ".join(result.warnings) or None
        return msg.status


async def _record_applied(db: AsyncSession, applied: dict, matches: list) -> None:
    """The email says the user applied (Naukri's "You applied for 1 job on 12 Nov"): mark those jobs Applied on
    that day, as if the user had pressed Applied. A job already applied to, or merged as a duplicate, is left."""
    for index, day in applied.items():
        uj = await db.scalar(select(UserJob).where(UserJob.job_id == matches[index].job_id).with_for_update())
        if uj is None or uj.status in ("applied", "duplicate"):
            continue
        await applications.mark_applied(db, uj, on=day)
        if uj.status == "expired":
            uj.expired_at, uj.expired_by = None, None
        uj.status = "applied"
        uj.version += 1


async def record_failure(inbound_message_id: UUID, user_id: UUID, error: Exception) -> None:
    async with user_scope(user_id) as db:
        msg = await db.get(InboundMessage, inbound_message_id)
        if msg is not None:
            msg.error = f"{type(error).__name__}: {error}"[:500]


@app.task(
    name=PARSE_ALERT,
    queue="ingest",
    # About 30 s, then growing: 32 s, 34 s, 38 s, 46 s.
    retry=procrastinate.RetryStrategy(max_attempts=5, wait=30, exponential_wait=2),
)
async def parse_alert(inbound_message_id: str, user_id: str) -> None:
    mid, uid = UUID(inbound_message_id), UUID(user_id)
    try:
        status = await process_message(mid, uid)
    except Exception as e:
        await record_failure(mid, uid, e)  # visible in the Inbox while retries continue
        raise
    log.info("inbound message %s: %s", inbound_message_id, status)
    if status == "parsed":
        await queue_scoring(uid, "new alert", inbound_message_id=mid, delay=0)


# --- Housekeeping ------------------------------------------------------------------------------------

SWEEP = "ingestion.sweep_inbound"
PURGE = "ingestion.purge_raw_email"
# A message just accepted may not have its parse task queued yet; leave it alone for this long.
SWEEP_GRACE = timedelta(minutes=2)
_GAVE_UP = ("failed", "cancelled", "aborted")


async def _user_ids() -> list[UUID]:
    # users has no RLS. Private tables do (FORCE), so each user's rows are handled inside user_scope.
    async with sessionmaker()() as db:
        return list(await db.scalars(select(User.id).order_by(User.created_at)))


async def _parse_task_status(db: AsyncSession, message_ids: list[str]) -> dict[str, str]:
    """The latest parse_alert task's status for each message (procrastinate_jobs has no RLS)."""
    rows = await db.execute(
        text(
            "select distinct on (args->>'inbound_message_id') args->>'inbound_message_id', status::text "
            "from procrastinate_jobs where task_name = :task and args->>'inbound_message_id' = any(:ids) "
            "order by args->>'inbound_message_id', id desc"
        ),
        {"task": PARSE_ALERT, "ids": message_ids},
    )
    return {mid: status for mid, status in rows.all()}


async def sweep_user(user_id: UUID) -> dict[str, int]:
    """Find this user's messages still 'accepted': queue them again if their parse task was lost, or mark
    them 'failed' once it has used up its retries. Returns how many of each."""
    requeue: list[UUID] = []
    failed = 0
    async with user_scope(user_id) as db:
        msgs = list(
            await db.scalars(
                select(InboundMessage)
                .where(InboundMessage.status == "accepted")
                .where(InboundMessage.received_at < datetime.now(UTC) - SWEEP_GRACE)
                .with_for_update(skip_locked=True)
            )
        )
        tasks = await _parse_task_status(db, [str(m.id) for m in msgs])
        for m in msgs:
            status = tasks.get(str(m.id))
            if status in ("todo", "doing"):
                continue
            if status in _GAVE_UP:
                m.status, m.processed_at = "failed", datetime.now(UTC)
                m.error = m.error or "Parsing failed after several attempts"
                failed += 1
            else:
                requeue.append(m.id)
    for mid in requeue:
        await queue_parse(mid, user_id)
    return {"requeued": len(requeue), "failed": failed}


async def purge_user(user_id: UUID, older_than: datetime) -> int:
    """Delete this user's raw emails received before `older_than`. The message rows (the Inbox) stay."""
    async with user_scope(user_id) as db:
        result = await db.execute(delete(InboundRaw).where(InboundRaw.created_at < older_than))
        return result.rowcount or 0


@app.periodic(cron="*/5 * * * *", periodic_id="sweep")
@app.task(name=SWEEP, queue="ingest", queueing_lock=SWEEP)
async def sweep_inbound(timestamp: int) -> None:
    totals = {"requeued": 0, "failed": 0}
    for uid in await _user_ids():
        for k, v in (await sweep_user(uid)).items():
            totals[k] += v
    if any(totals.values()):
        log.info("inbound sweep: %s", totals)


@app.periodic(cron="0 2 * * *", periodic_id="purge")  # 02:00 in the worker's time zone (UTC in Docker)
@app.task(name=PURGE, queue="ingest", queueing_lock=PURGE)
async def purge_raw_email(timestamp: int) -> None:
    cutoff = datetime.fromtimestamp(timestamp, UTC) - timedelta(days=get_settings().raw_email_retention_days)
    deleted = 0
    for uid in await _user_ids():
        deleted += await purge_user(uid, cutoff)
    log.info("purged %d raw emails received before %s", deleted, cutoff.isoformat())
