"""The user's jobs: list, filters, detail, status changes, pasted descriptions, and the local .eml upload."""

import base64
import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import user_scope
from app.modules.ingestion.tasks import parse_alert
from app.modules.jobs.models import UserJob
from app.modules.users.models import User
from tests.conftest import auth, signup
from tests.test_ingestion import EMAILS, INVITE, LINKEDIN, payload, post_inbound, queued_tasks

NAUKRI = (EMAILS / "naukri-alert-recommended-jobs-2026-09-21.eml").read_bytes()
DESCRIPTION = "We are hiring a VP of Engineering to lead 120 engineers across payments and lending. " * 2


async def deliver(client, account, raw: bytes, dkim_domain: str = "linkedin.com") -> None:
    """Receive an alert the way the email worker sends it, then run the parse task the worker would run."""
    r = await post_inbound(client, payload(raw, account["address"], dkim_domain=dkim_domain))
    assert r.status_code == 202, r.text
    mid = r.json()["inbound_message_id"]
    (task,) = [t for t in await queued_tasks() if json.loads(t["args"])["inbound_message_id"] == mid]
    await parse_alert(**json.loads(task["args"]))


async def jobs(client, account, **params) -> dict:
    r = await client.get("/api/v1/jobs", params=params, headers=account["headers"])
    assert r.status_code == 200, r.text
    return r.json()


async def find(client, account, title: str) -> dict:
    (item,) = [j for j in (await jobs(client, account, status="all"))["items"] if j["job"]["title"] == title]
    return item


# --- List and filters --------------------------------------------------------------------------------


async def test_jobs_from_an_alert_are_listed_newest_first(client, account):
    await deliver(client, account, LINKEDIN)

    body = await jobs(client, account)
    assert body["total"] == 6 and len(body["items"]) == 6
    first = next(j for j in body["items"] if j["job"]["company"] == "Cognizant")
    assert (first["status"], first["lead"], first["version"]) == ("new", "alert", 1)
    assert first["job"]["sources"] == [
        {"source": "linkedin", "url": "https://www.linkedin.com/jobs/view/4484103275/"}
    ]
    assert first["has_apply_link"] is False


async def test_filters_by_source_lead_status_and_search(client, account):
    await deliver(client, account, LINKEDIN)
    await deliver(client, account, NAUKRI, dkim_domain="naukri.com")
    await deliver(client, account, INVITE, dkim_domain="naukri.com")

    assert (await jobs(client, account))["total"] == 18
    assert (await jobs(client, account, source="linkedin"))["total"] == 6
    assert (await jobs(client, account, source="naukri"))["total"] == 12  # recruiter invites included
    assert (await jobs(client, account, lead="recruiter_invite"))["total"] == 1
    assert (await jobs(client, account, lead="recommendation"))["total"] == 11

    cognizant = await jobs(client, account, q="cognizant")
    assert [j["job"]["title"] for j in cognizant["items"]] == ["SEG & India CFO"]
    assert (await jobs(client, account, q="jaipur"))["total"] == 1  # location
    assert (await jobs(client, account, q="100%_"))["total"] == 0  # LIKE wildcards are literal

    page = await jobs(client, account, limit=5, offset=15)
    assert (page["total"], len(page["items"]), page["offset"]) == (18, 3, 15)


async def test_filters_by_the_users_calendar_day(client, account):
    await deliver(client, account, LINKEDIN)
    long_ago = datetime.now(UTC) - timedelta(days=40)
    async with user_scope(account["id"]) as db:
        (await db.execute(update(UserJob).where(UserJob.lead == "alert").values(first_seen_at=long_ago)))

    # The user's calendar days, not UTC ones (the test failed between midnight IST and midnight UTC).
    async with user_scope(account["id"]) as db:
        tz = ZoneInfo(await db.scalar(select(User.timezone).where(User.id == account["id"])) or "UTC")
    today = datetime.now(tz).date().isoformat()
    assert (await jobs(client, account, **{"from": today}))["total"] == 0
    old = long_ago.astimezone(tz).date()
    assert (await jobs(client, account, **{"from": str(old - timedelta(days=1)), "to": str(old)}))[
        "total"
    ] == 6


async def test_bad_filters_are_refused(client, account):
    for params in (
        {"status": "archived"},
        {"limit": 0},
        {"from": "2026-10-31", "to": "2026-10-01"},
        {"q": "x" * 101},
    ):
        r = await client.get("/api/v1/jobs", params=params, headers=account["headers"])
        assert r.status_code == 422, params
        assert r.json()["error"]["code"] == "validation_error"


async def test_stats_count_new_active_and_ignored(client, account):
    await deliver(client, account, LINKEDIN)
    job = (await jobs(client, account))["items"][0]
    await client.patch(
        f"/api/v1/jobs/{job['id']}", json={"status": "ignored", "version": 1}, headers=account["headers"]
    )

    r = await client.get("/api/v1/jobs/stats", headers=account["headers"])
    # No resume yet, so nothing is scored: every active job is in the "not scored yet" tab.
    assert r.json() == {
        "new": 5,
        "active": 5,
        "ignored": 1,
        "applied": 0,
        "expired": 0,
        "last_7_days": 5,
        "review": 0,
        "top": 0,
        "other": 0,
        "unscored": 5,
        "ready": 0,
        "needs_input": 0,
    }


# --- Detail, status, description ---------------------------------------------------------------------


async def test_detail_has_the_private_apply_link_and_full_description(client, account):
    await deliver(client, account, INVITE, dkim_domain="naukri.com")
    (item,) = (await jobs(client, account))["items"]

    r = await client.get(f"/api/v1/jobs/{item['id']}", headers=account["headers"])
    assert r.status_code == 200
    d = r.json()
    assert d["lead"] == "recruiter_invite" and "applyBroadcastMail" in d["apply_url"]
    assert d["has_apply_link"] is True
    assert d["job"]["sources"] == [{"source": "naukri_rdx", "url": None}]
    assert d["job"]["description_source"] == "alert" and d["job"]["description_complete"] is True


async def test_card_lines_about_the_user_are_on_the_detail(client, account):
    await deliver(client, account, LINKEDIN)
    item = await find(client, account, "SEG & India CFO")
    d = (await client.get(f"/api/v1/jobs/{item['id']}", headers=account["headers"])).json()
    assert d["card_lines"] == ["2 connections"]
    assert d["inbound_message_id"] is not None


async def test_ignore_and_restore_with_version_check(client, account):
    await deliver(client, account, LINKEDIN)
    item = await find(client, account, "Chief Engineer")
    url = f"/api/v1/jobs/{item['id']}"

    r = await client.patch(url, json={"status": "ignored", "version": 1}, headers=account["headers"])
    assert (r.status_code, r.json()["status"], r.json()["version"]) == (200, "ignored", 2)
    assert (await jobs(client, account))["total"] == 5  # hidden from the default list
    assert (await jobs(client, account, status="ignored"))["total"] == 1

    stale = await client.patch(url, json={"status": "seen", "version": 1}, headers=account["headers"])
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "version_conflict")

    r = await client.patch(url, json={"status": "seen", "version": 2}, headers=account["headers"])
    assert (r.json()["status"], r.json()["version"]) == ("seen", 3)
    # Unchanged status: no new version, so a second tab doesn't get a needless conflict.
    r = await client.patch(url, json={"status": "seen", "version": 3}, headers=account["headers"])
    assert r.json()["version"] == 3


async def test_a_new_alert_keeps_the_ignored_status(client, account):
    await deliver(client, account, LINKEDIN)
    item = await find(client, account, "Chief Engineer")
    await client.patch(
        f"/api/v1/jobs/{item['id']}", json={"status": "ignored", "version": 1}, headers=account["headers"]
    )
    again = payload(LINKEDIN, account["address"])
    again["message_id"] = "<second-copy@linkedin.com>"
    r = await post_inbound(client, again)
    task = [t for t in await queued_tasks() if r.json()["inbound_message_id"] in t["args"]]
    await parse_alert(**json.loads(task[0]["args"]))

    assert (await find(client, account, "Chief Engineer"))["status"] == "ignored"


async def test_pasted_description_is_the_users_own(client, account):
    await deliver(client, account, LINKEDIN)
    item = await find(client, account, "Chief Engineer")

    r = await client.post(
        f"/api/v1/jobs/{item['id']}/description",
        json={"text": f"  {DESCRIPTION}  ", "version": 1},
        headers=account["headers"],
    )
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    assert (job["description"], job["description_source"], r.json()["version"]) == (
        DESCRIPTION.strip(),
        "you",
        2,
    )

    # Another user who received the same alert still sees the catalog's version (none for LinkedIn cards).
    other = await signup(client, name="Bob")
    client.cookies.clear()
    bob = {"headers": auth(other["access_token"])}
    me = (await client.get("/api/v1/me", headers=bob["headers"])).json()
    bob["address"] = me["forwarding_address"]
    await deliver(client, bob, LINKEDIN)
    theirs = await find(client, bob, "Chief Engineer")
    d = (await client.get(f"/api/v1/jobs/{theirs['id']}", headers=bob["headers"])).json()
    assert d["job"]["description"] is None and d["job"]["description_source"] is None


async def test_description_errors(client, account):
    await deliver(client, account, LINKEDIN)
    item = await find(client, account, "Chief Engineer")
    url = f"/api/v1/jobs/{item['id']}/description"

    short = await client.post(
        url, json={"text": "  too short  " + " " * 60, "version": 1}, headers=account["headers"]
    )
    assert short.status_code == 422
    stale = await client.post(url, json={"text": DESCRIPTION, "version": 9}, headers=account["headers"])
    assert stale.status_code == 409


async def test_unknown_job_is_not_found(client, account):
    missing = "00000000-0000-0000-0000-000000000000"
    h = account["headers"]
    assert (await client.get(f"/api/v1/jobs/{missing}", headers=h)).status_code == 404
    assert (
        await client.patch(f"/api/v1/jobs/{missing}", json={"status": "seen", "version": 1}, headers=h)
    ).status_code == 404
    r = await client.post(
        f"/api/v1/jobs/{missing}/description", json={"text": DESCRIPTION, "version": 1}, headers=h
    )
    assert r.json()["error"]["code"] == "not_found"


async def test_jobs_need_sign_in(client):
    for method, path in [("get", "/api/v1/jobs"), ("get", "/api/v1/jobs/stats")]:
        assert (await getattr(client, method)(path)).status_code == 401


async def test_jobs_are_private_to_each_user(client, account):
    await deliver(client, account, LINKEDIN)
    item = (await jobs(client, account))["items"][0]
    other = await signup(client, name="Mallory")
    client.cookies.clear()
    h = auth(other["access_token"])

    assert (await client.get("/api/v1/jobs", headers=h)).json()["total"] == 0
    assert (await client.get(f"/api/v1/jobs/{item['id']}", headers=h)).status_code == 404
    r = await client.patch(f"/api/v1/jobs/{item['id']}", json={"status": "ignored", "version": 1}, headers=h)
    assert r.status_code == 404
    r = await client.post(
        f"/api/v1/jobs/{item['id']}/description", json={"text": DESCRIPTION, "version": 1}, headers=h
    )
    assert r.status_code == 404
    assert (await find(client, account, item["job"]["title"]))["status"] == "new"


# --- Local .eml upload -------------------------------------------------------------------------------


def upload_body(raw: bytes) -> dict:
    return {"raw_mime_base64": base64.b64encode(raw).decode()}


async def test_upload_delivers_a_saved_email_locally(client, account, monkeypatch):
    monkeypatch.setattr(get_settings(), "env", "local")
    assert (await client.get("/api/v1/mail", headers=account["headers"])).json()["upload_enabled"] is True

    r = await client.post("/api/v1/inbox/upload", json=upload_body(NAUKRI), headers=account["headers"])
    assert r.status_code == 202, r.text
    (task,) = await queued_tasks()
    await parse_alert(**json.loads(task["args"]))

    (m,) = (await client.get("/api/v1/inbox/messages", headers=account["headers"])).json()
    assert (m["channel"], m["status"], m["cards_found"]) == ("paste", "parsed", 11)
    assert (await jobs(client, account))["total"] == 11

    again = await client.post("/api/v1/inbox/upload", json=upload_body(NAUKRI), headers=account["headers"])
    assert (again.status_code, again.json()["error"]["code"]) == (422, "duplicate")


async def test_upload_refuses_other_senders_and_junk(client, account, monkeypatch):
    monkeypatch.setattr(get_settings(), "env", "local")
    junk = await client.post(
        "/api/v1/inbox/upload", json={"raw_mime_base64": "%%%"}, headers=account["headers"]
    )
    assert junk.json()["error"]["code"] == "unreadable"
    spam = b"From: offers@example.com\r\nSubject: Win\r\nMessage-ID: <s@x>\r\n\r\nhello"
    r = await client.post("/api/v1/inbox/upload", json=upload_body(spam), headers=account["headers"])
    assert (r.status_code, r.json()["error"]["code"]) == (422, "sender_not_allowed")


async def test_upload_does_not_exist_outside_local(client, account):
    assert get_settings().env == "test"
    assert (await client.get("/api/v1/mail", headers=account["headers"])).json()["upload_enabled"] is False
    r = await client.post("/api/v1/inbox/upload", json=upload_body(LINKEDIN), headers=account["headers"])
    assert r.status_code == 404
    assert await queued_tasks() == []
