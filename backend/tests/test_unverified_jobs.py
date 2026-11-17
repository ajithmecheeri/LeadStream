"""Unverified jobs (2026-11-08): jobs only a hand forward or an AI assistant's list describe say so, until a
portal, feed or API listing of the same job confirms them."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.db import user_scope
from app.modules.catalog.parsers import JobCard
from app.modules.catalog.service import upsert_cards
from app.modules.jobs.linking import link_cards
from tests.test_duplicates import card, detail, listed


async def link(user_id: UUID, one: JobCard, verified: bool) -> UUID:
    async with user_scope(user_id) as db:
        (uj,) = await link_cards(db, user_id, [one], await upsert_cards(db, [one], verified=verified))
        return uj


async def test_an_assistant_job_is_unverified_until_a_portal_lists_it(client, account):
    uid = account["id"]
    uj = await link(uid, card("Head of Product", "SAP", source="ai_assistant"), verified=False)
    assert (await detail(client, account, uj))["job"]["verified"] is False
    assert [j["job"]["verified"] for j in await listed(client, account)] == [False]

    async with user_scope(uid) as db:
        portal = card("Head of Product", "SAP")
        await link_cards(db, uid, [portal], await upsert_cards(db, [portal]))
    assert (await detail(client, account, uj))["job"]["verified"] is True


async def test_a_job_from_a_portal_alert_is_verified(client, account):
    uj = await link(account["id"], card("VP Engineering", "Acme"), verified=True)
    assert (await detail(client, account, uj))["job"]["verified"] is True
    r = await client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000", headers=account["headers"])
    assert r.status_code == 404


async def assistant_job(user_id: UUID, title: str, **kw) -> UUID:
    return await link(user_id, card(title, "Acme", source="ai_assistant", **kw), verified=False)


async def expiry(client, account, user_job_id) -> dict | None:
    job = await detail(client, account, user_job_id)
    return next((t for t in job["todos"] if t["kind"] == "expiry"), None)


async def test_doubts_about_an_assistant_posting_warn_until_you_say_it_is_open(client, account):
    uid, now = account["id"], datetime.now(UTC)
    conflict = {
        "posted": "says posted yesterday; another copy says 23 days ago",
        "posting": {"conflict": True},
    }
    unclear = await assistant_job(uid, "VP Engineering", details=conflict, posted_at=now - timedelta(days=23))
    closed = await assistant_job(
        uid,
        "Director Platform",
        details={"posting": {"closes_on": (now - timedelta(days=2)).date().isoformat()}},
    )
    today = await assistant_job(
        uid, "Director Data", details={"posting": {"closes_on": now.date().isoformat()}}
    )
    old = await assistant_job(
        uid, "Head of AI", details={"posted": "5 weeks ago"}, posted_at=now - timedelta(days=35)
    )
    recent = await assistant_job(
        uid, "Head of Data", details={"posted": "3 days ago"}, posted_at=now - timedelta(days=3)
    )

    todo = await expiry(client, account, unclear)
    assert todo["title"] == "This job may have expired" and "posting dates disagree" in todo["detail"]
    assert (await expiry(client, account, closed))["title"] == "This job may have closed"
    assert (await expiry(client, account, today))["title"] == "Applications close today"
    assert "about 35 days ago" in (await expiry(client, account, old))["detail"]
    assert await expiry(client, account, recent) is None
    flagged = {j["id"] for j in await listed(client, account) if j["may_have_expired"]}
    assert flagged == {str(unclear), str(closed), str(today), str(old)}

    r = await client.post(f"/api/v1/jobs/{unclear}/still-open", headers=account["headers"])
    assert r.status_code == 200, r.text
    assert await expiry(client, account, unclear) is None


async def test_an_old_posting_is_not_in_doubt_once_a_portal_lists_it(client, account):
    uid, now = account["id"], datetime.now(UTC)
    old = await assistant_job(
        uid, "Head of AI", details={"posted": "5 weeks ago"}, posted_at=now - timedelta(days=35)
    )
    async with user_scope(uid) as db:
        portal = card("Head of AI", "Acme")
        await link_cards(db, uid, [portal], await upsert_cards(db, [portal]))
    assert await expiry(client, account, old) is None
