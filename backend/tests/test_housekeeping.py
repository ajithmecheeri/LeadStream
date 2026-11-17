"""Worker housekeeping: the sweep that rescues or fails stuck messages, and the raw-email purge."""

import json
import time
from datetime import UTC, datetime, timedelta

import asyncpg
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import user_scope
from app.modules.ingestion import service
from app.modules.ingestion.models import InboundMessage, InboundRaw
from app.modules.ingestion.tasks import parse_alert, purge_raw_email, sweep_inbound
from tests.conftest import auth, signup
from tests.test_ingestion import LINKEDIN, payload, post_inbound, queued_tasks
from tests.test_isolation import _dsn


async def backdate(user_id, minutes: int) -> None:
    async with user_scope(user_id) as db:
        await db.execute(
            update(InboundMessage).values(received_at=datetime.now(UTC) - timedelta(minutes=minutes))
        )


async def message(user_id) -> InboundMessage:
    async with user_scope(user_id) as db:
        return (await db.execute(select(InboundMessage))).scalar_one()


async def set_task_status(status: str) -> None:
    conn = await asyncpg.connect(_dsn(get_settings().database_url))
    try:
        await conn.execute(f"update procrastinate_jobs set status = '{status}'")
    finally:
        await conn.close()


async def test_sweep_requeues_a_message_whose_task_was_lost(client, account, monkeypatch):
    async def broken_defer(*_, **__):
        raise ConnectionError("queue down")

    monkeypatch.setattr(service, "defer", broken_defer)
    await post_inbound(client, payload(LINKEDIN, account["address"]))
    monkeypatch.undo()
    assert await queued_tasks() == []

    await sweep_inbound(timestamp=int(time.time()))
    assert await queued_tasks() == []  # too recent: the API may still be queueing it

    await backdate(account["id"], minutes=10)
    await sweep_inbound(timestamp=int(time.time()))
    (task,) = await queued_tasks()
    assert task["task_name"] == "ingestion.parse_alert"

    await parse_alert(**json.loads(task["args"]))
    assert (await message(account["id"])).status == "parsed"


async def test_sweep_leaves_queued_messages_alone(client, account):
    await post_inbound(client, payload(LINKEDIN, account["address"]))
    await backdate(account["id"], minutes=10)

    await sweep_inbound(timestamp=int(time.time()))

    assert len(await queued_tasks()) == 1
    assert (await message(account["id"])).status == "accepted"


async def test_sweep_marks_a_message_failed_after_its_retries(client, account):
    await post_inbound(client, payload(LINKEDIN, account["address"]))
    await backdate(account["id"], minutes=10)
    await set_task_status("failed")

    await sweep_inbound(timestamp=int(time.time()))

    m = await message(account["id"])
    assert (m.status, m.error) == ("failed", "Parsing failed after several attempts")
    assert len(await queued_tasks()) == 1  # not queued again
    inbox = (await client.get("/api/v1/inbox/messages", headers=account["headers"])).json()
    assert inbox[0]["status"] == "failed"


async def test_purge_deletes_old_raw_emails_for_every_user(client, account):
    other = await signup(client, name="Bob")
    client.cookies.clear()
    bob_me = (await client.get("/api/v1/me", headers=auth(other["access_token"]))).json()
    await post_inbound(client, payload(LINKEDIN, account["address"]))
    await post_inbound(client, payload(LINKEDIN, bob_me["forwarding_address"]))
    async with user_scope(account["id"]) as db:
        await db.execute(update(InboundRaw).values(created_at=datetime.now(UTC) - timedelta(days=91)))

    await purge_raw_email(timestamp=int(time.time()))

    async with user_scope(account["id"]) as db:
        assert (await db.execute(select(InboundRaw))).all() == []
        assert len((await db.execute(select(InboundMessage))).all()) == 1  # the Inbox keeps the message
    async with user_scope(bob_me["id"]) as db:
        assert len((await db.execute(select(InboundRaw))).all()) == 1  # Bob's is recent


async def test_a_purged_message_can_no_longer_be_parsed(client, account):
    await post_inbound(client, payload(LINKEDIN, account["address"]))
    async with user_scope(account["id"]) as db:
        await db.execute(update(InboundRaw).values(created_at=datetime.now(UTC) - timedelta(days=91)))
    await purge_raw_email(timestamp=int(time.time()))

    (task,) = await queued_tasks()
    await parse_alert(**json.loads(task["args"]))
    m = await message(account["id"])
    assert m.status == "failed" and "deleted" in m.error  # so the sweep doesn't retry it forever
