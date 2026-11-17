"""The in-app bell (milestone 6.2): new top matches, possible duplicates, follow-ups due and jobs that may have
expired, newest first, with an unread count that clears when the bell is opened."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.core.db import user_scope
from app.modules.applications.models import Application
from app.modules.matching.models import JobMatch
from tests.test_duplicates import card, detail, link
from tests.test_unverified_jobs import assistant_job


async def bell(client, account) -> dict:
    r = await client.get("/api/v1/notifications/bell", headers=account["headers"])
    assert r.status_code == 200, r.text
    return r.json()


async def test_the_bell_lists_what_needs_attention(client, account):
    uid = account["id"]
    (top,) = await link(uid, card("Head of Product", "Acme"))
    (weak,) = await link(uid, card("Engineering Manager", "Beta"))
    async with user_scope(uid) as db:
        db.add(JobMatch(user_job_id=top, user_id=uid, band="strong", score=92))
        db.add(JobMatch(user_job_id=weak, user_id=uid, band="good", score=70))
    (first,) = await link(uid, card("VP Engineering", "Gamma"))
    # The same company in another city: a possible duplicate, shown once.
    (second,) = await link(uid, card("VP Engineering", "Gamma", "Pune"))
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    closed = await assistant_job(uid, "Director Platform", details={"posting": {"closes_on": yesterday}})
    (applied,) = await link(uid, card("Director Data", "Delta"))
    job = await detail(client, account, applied)
    r = await client.patch(
        f"/api/v1/jobs/{applied}",
        json={"status": "applied", "version": job["version"]},
        headers=account["headers"],
    )
    assert r.status_code == 200, r.text
    async with user_scope(uid) as db:
        await db.execute(
            update(Application).values(follow_up_on=datetime.now(UTC).date() - timedelta(days=1))
        )

    got = await bell(client, account)
    kinds = {i["kind"]: i for i in got["items"]}
    assert set(kinds) == {"strong", "duplicate", "follow_up", "expiry"}
    assert kinds["strong"]["title"] == "Top match, 92%" and kinds["strong"]["user_job_id"] == str(top)
    assert kinds["expiry"]["title"] == "This job may have closed" and kinds["expiry"]["user_job_id"] == str(
        closed
    )
    assert kinds["follow_up"]["user_job_id"] == str(applied)
    assert kinds["duplicate"]["user_job_id"] in {str(first), str(second)}
    assert [i["kind"] for i in got["items"]].count("duplicate") == 1
    assert got["unread"] == 4 and all(i["unread"] for i in got["items"])
    ats = [i["at"] for i in got["items"]]
    assert ats == sorted(ats, reverse=True)

    r = await client.post("/api/v1/notifications/bell/seen", headers=account["headers"])
    assert r.status_code == 204
    seen = await bell(client, account)
    assert seen["unread"] == 0 and len(seen["items"]) == 4


async def test_the_bell_needs_a_signed_in_user(client):
    r = await client.get("/api/v1/notifications/bell")
    assert r.status_code == 401
    assert (await client.post("/api/v1/notifications/bell/seen")).status_code == 401
