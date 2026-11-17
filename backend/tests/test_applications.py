"""Milestone 5: Applied and Expired jobs, the applications tracker, contacts, to-dos, why a match isn't 100%,
and the super admin's settings."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.admin import set_role
from app.core.db import sessionmaker, user_scope
from app.modules.ingestion.tasks import parse_alert
from app.modules.jobs.expiry import expire_old_jobs
from app.modules.jobs.models import UserJob
from app.modules.matching.scoring import JobInput, ResumeInput, points_lost, skill_split
from app.modules.users.models import AuditEvent
from tests.conftest import PASSWORD, auth
from tests.test_ingestion import INVITE, LINKEDIN, payload, post_inbound, queued_tasks
from tests.test_jobs import deliver, find, jobs
from tests.test_matching import match_profiles, run_scoring, setup_user


async def set_status(client, account, item: dict, status: str, version: int | None = None):
    return await client.patch(
        f"/api/v1/jobs/{item['id']}",
        json={"status": status, "version": version or item["version"]},
        headers=account["headers"],
    )


async def detail(client, account, user_job_id: str) -> dict:
    r = await client.get(f"/api/v1/jobs/{user_job_id}", headers=account["headers"])
    assert r.status_code == 200, r.text
    return r.json()


async def applications(client, account, **params) -> dict:
    r = await client.get("/api/v1/applications", params=params, headers=account["headers"])
    assert r.status_code == 200, r.text
    return r.json()


async def age_job(account, user_job_id: str, days: int) -> None:
    when = datetime.now(UTC) - timedelta(days=days)
    async with user_scope(account["id"]) as db:
        await db.execute(update(UserJob).where(UserJob.id == user_job_id).values(last_seen_at=when))


# --- Applied -----------------------------------------------------------------------------------------


async def test_mark_applied_moves_the_job_to_the_applied_queue(client, account):
    await setup_user(client, account)
    await run_scoring(account)
    item = await find(client, account, "Chief Engineer")
    best = item["match"]["best_resume_id"]

    r = await set_status(client, account, item, "applied")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "applied" and d["application"]["status"] == "applied"
    assert d["application"]["applied_on"]
    assert d["todos"] == []  # readiness blockers don't apply once you've applied

    assert item["id"] not in [j["id"] for j in (await jobs(client, account, tab="top"))["items"]]
    assert [j["id"] for j in (await jobs(client, account, status="applied"))["items"]] == [item["id"]]
    stats = (await client.get("/api/v1/jobs/stats", headers=account["headers"])).json()
    assert stats["applied"] == 1

    apps = await applications(client, account)
    (a,) = apps["items"]
    assert a["job"]["title"] == "Chief Engineer" and a["resume_id"] == best
    assert a["cover_letter_label"] == "Tech"
    assert apps["counts"] == {"applied": 1}


async def test_undo_applied_until_the_application_has_updates(client, account):
    await deliver(client, account, LINKEDIN)
    item = await find(client, account, "Chief Engineer")
    applied = (await set_status(client, account, item, "applied")).json()

    undone = await set_status(client, account, applied, "seen")
    assert undone.status_code == 200 and undone.json()["application"] is None
    assert (await applications(client, account))["total"] == 0

    again = (await set_status(client, account, undone.json(), "applied")).json()
    app_id = again["application"]["id"]
    r = await client.patch(
        f"/api/v1/applications/{app_id}",
        json={"status": "interviewing", "version": 1},
        headers=account["headers"],
    )
    assert r.status_code == 200
    refused = await set_status(client, account, again, "seen")
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "application_has_history")


# --- The tracker -------------------------------------------------------------------------------------


async def _applied(client, account, title: str = "Chief Engineer") -> dict:
    item = await find(client, account, title)
    return (await set_status(client, account, item, "applied")).json()["application"]


async def test_status_changes_and_notes_build_the_timeline(client, account):
    await deliver(client, account, LINKEDIN)
    app = await _applied(client, account)
    url = f"/api/v1/applications/{app['id']}"
    h = account["headers"]

    r = await client.patch(url, json={"status": "interviewing", "version": 1}, headers=h)
    assert (r.json()["status"], r.json()["version"]) == ("interviewing", 2)
    r = await client.post(f"{url}/notes", json={"text": "  First round with the VP on Monday "}, headers=h)
    assert r.status_code == 201
    r = await client.patch(url, json={"status": "offer", "version": 2}, headers=h)

    events = r.json()["events"]
    assert [(e["kind"], e["to_status"]) for e in events] == [
        ("applied", "applied"),
        ("status", "interviewing"),
        ("note", None),
        ("status", "offer"),
    ]
    assert events[2]["note"] == "First round with the VP on Monday"
    assert events[3]["from_status"] == "interviewing"

    stale = await client.patch(url, json={"status": "accepted", "version": 1}, headers=h)
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "version_conflict")


async def test_follow_up_due_comes_first_and_shows_as_a_to_do(client, account):
    await deliver(client, account, LINKEDIN)
    first = await _applied(client, account, "Chief Engineer")
    second = await _applied(client, account, "SEG & India CFO")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    r = await client.patch(
        f"/api/v1/applications/{first['id']}",
        json={"follow_up_on": yesterday, "version": 1},
        headers=account["headers"],
    )
    assert r.json()["follow_up_due"] is True
    assert r.json()["events"][-1] == {**r.json()["events"][-1], "kind": "follow_up", "note": yesterday}

    listed = await applications(client, account)
    assert [a["id"] for a in listed["items"]] == [first["id"], second["id"]]
    assert listed["follow_ups_due"] == 1
    assert (await applications(client, account, due="true"))["total"] == 1

    job = await detail(client, account, r.json()["job"]["user_job_id"])
    assert [t["kind"] for t in job["todos"]] == ["follow_up"] and job["todo"] == 1

    # A closed application has nothing to follow up.
    r = await client.patch(
        f"/api/v1/applications/{first['id']}",
        json={"status": "rejected", "version": 2},
        headers=account["headers"],
    )
    assert r.json()["follow_up_due"] is False
    cleared = await client.patch(
        f"/api/v1/applications/{first['id']}",
        json={"follow_up_on": None, "version": 3},
        headers=account["headers"],
    )
    assert cleared.json()["follow_up_on"] is None


async def test_filters_by_status_and_date_applied(client, account):
    await deliver(client, account, LINKEDIN)
    a = await _applied(client, account, "Chief Engineer")
    await _applied(client, account, "SEG & India CFO")
    await client.patch(
        f"/api/v1/applications/{a['id']}",
        json={"applied_on": "2026-09-15", "status": "no_response", "version": 1},
        headers=account["headers"],
    )

    assert (await applications(client, account, status="no_response"))["total"] == 1
    september = await applications(client, account, **{"from": "2026-09-01", "to": "2026-09-30"})
    assert [x["id"] for x in september["items"]] == [a["id"]]
    year = await applications(client, account, **{"from": "2026-01-01", "to": "2026-12-31"})
    assert year["total"] == 2
    assert year["counts"] == {"no_response": 1, "applied": 1}

    bad = await client.get(
        "/api/v1/applications", params={"from": "2026-10-02", "to": "2026-10-01"}, headers=account["headers"]
    )
    assert bad.status_code == 422
    assert (
        await client.get("/api/v1/applications", params={"status": "maybe"}, headers=account["headers"])
    ).status_code == 422


async def test_application_errors(client, account):
    await deliver(client, account, LINKEDIN)
    app = await _applied(client, account)
    h = account["headers"]
    url = f"/api/v1/applications/{app['id']}"
    unknown = "00000000-0000-0000-0000-000000000000"

    assert (await client.get(f"/api/v1/applications/{unknown}", headers=h)).status_code == 404
    r = await client.patch(url, json={"resume_id": unknown, "version": 1}, headers=h)
    assert r.status_code == 422
    assert (await client.post(f"{url}/notes", json={"text": "   "}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"status": "hired", "version": 1}, headers=h)).status_code == 422
    assert (await client.get("/api/v1/applications")).status_code == 401


async def test_applications_are_private(client, account):
    await deliver(client, account, LINKEDIN)
    app = await _applied(client, account)
    other = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": "someone-else@example.com",
            "first_name": "Someone",
            "last_name": "Else",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
            "accept_terms": True,
            "job_locations": ["Bengaluru"],
        },
    )
    h = auth(other.json()["access_token"])
    assert (await client.get(f"/api/v1/applications/{app['id']}", headers=h)).status_code == 404
    assert (await client.get("/api/v1/applications", headers=h)).json()["total"] == 0


# --- Expired -----------------------------------------------------------------------------------------


async def test_an_old_job_may_have_expired_until_you_say_it_is_open(client, account):
    await deliver(client, account, LINKEDIN)
    item = await find(client, account, "Chief Engineer")
    await age_job(account, item["id"], 31)

    d = await detail(client, account, item["id"])
    assert d["may_have_expired"] is True
    assert [t["key"] for t in d["todos"]] == ["expiry"] and "30 days" in d["todos"][0]["detail"]
    assert (await find(client, account, "Chief Engineer"))["todo"] == 1

    r = await client.post(f"/api/v1/jobs/{item['id']}/still-open", headers=account["headers"])
    assert r.status_code == 200 and r.json()["may_have_expired"] is False and r.json()["todos"] == []


async def test_mark_expired_and_restore(client, account):
    await deliver(client, account, LINKEDIN)
    item = await find(client, account, "Chief Engineer")
    r = await set_status(client, account, item, "expired")
    assert (r.json()["status"], r.json()["expired_by"]) == ("expired", "user")
    assert (await jobs(client, account))["total"] == 5
    assert (await jobs(client, account, status="expired"))["total"] == 1

    no = await client.post(f"/api/v1/jobs/{item['id']}/still-open", headers=account["headers"])
    assert (no.status_code, no.json()["error"]["code"]) == (422, "not_active")

    back = await set_status(client, account, r.json(), "seen")
    assert (back.json()["status"], back.json()["expired_by"], back.json()["may_have_expired"]) == (
        "seen",
        None,
        False,
    )


async def test_the_daily_task_expires_old_jobs_but_never_applied_ones(client, account):
    await deliver(client, account, LINKEDIN)
    applied = await find(client, account, "SEG & India CFO")
    await set_status(client, account, applied, "applied")
    async with user_scope(account["id"]) as db:
        await db.execute(update(UserJob).values(last_seen_at=datetime.now(UTC) - timedelta(days=50)))
    fresh = await find(client, account, "Chief Engineer")
    await age_job(account, fresh["id"], 10)

    assert await expire_old_jobs(account["id"], 45) == 4
    assert (await jobs(client, account, status="expired"))["total"] == 4
    assert (await find(client, account, "SEG & India CFO"))["status"] == "applied"
    assert (await find(client, account, "Chief Engineer"))["status"] == "new"
    assert (await find(client, account, "Sr. Vice President- Projects"))["expired_by"] == "auto"


async def test_a_new_alert_revives_an_automatic_expiry_but_not_yours(client, account):
    await deliver(client, account, LINKEDIN)
    mine = await find(client, account, "Chief Engineer")
    await set_status(client, account, mine, "expired")
    async with user_scope(account["id"]) as db:
        await db.execute(update(UserJob).values(last_seen_at=datetime.now(UTC) - timedelta(days=50)))
    await expire_old_jobs(account["id"], 45)

    again = payload(LINKEDIN, account["address"])
    again["message_id"] = "<second-copy@linkedin.com>"
    r = await post_inbound(client, again)

    task = [t for t in await queued_tasks() if r.json()["inbound_message_id"] in t["args"]]

    await parse_alert(**json.loads(task[0]["args"]))

    assert (await find(client, account, "Chief Engineer"))["status"] == "expired"  # your choice stays
    revived = await find(client, account, "Sr. Vice President- Projects")
    assert (revived["status"], revived["expired_by"]) == ("seen", None)


# --- Contacts ----------------------------------------------------------------------------------------


async def test_contacts_on_a_job(client, account):
    await deliver(client, account, INVITE, dkim_domain="naukri.com")
    (item,) = (await jobs(client, account))["items"]
    url = f"/api/v1/jobs/{item['id']}/contacts"
    h = account["headers"]

    empty = (await client.get(url, headers=h)).json()
    assert empty["from_email"] == "Naukri Premium - Employer Services" and empty["items"] == []
    assert (await detail(client, account, item["id"]))["recruiter"] == "Naukri Premium - Employer Services"

    r = await client.post(
        url,
        json={"name": " Priya  Nair ", "role": "Recruiter", "linkedin_url": "linkedin.com/in/priya-nair-x"},
        headers=h,
    )
    assert r.status_code == 201
    (c,) = r.json()["items"]
    assert (c["name"], c["linkedin_url"]) == ("Priya Nair", "https://linkedin.com/in/priya-nair-x")

    r = await client.put(
        f"{url}/{c['id']}", json={"name": "Priya Nair", "email": "priya@example.com", "version": 1}, headers=h
    )
    assert r.json()["items"][0]["email"] == "priya@example.com" and r.json()["items"][0]["version"] == 2
    stale = await client.put(f"{url}/{c['id']}", json={"name": "P", "version": 1}, headers=h)
    assert stale.status_code == 409

    assert (await client.delete(f"{url}/{c['id']}", headers=h)).status_code == 204
    assert (await client.get(url, headers=h)).json()["items"] == []


async def test_contact_errors(client, account):
    await deliver(client, account, LINKEDIN)
    item = await find(client, account, "Chief Engineer")
    url = f"/api/v1/jobs/{item['id']}/contacts"
    h = account["headers"]
    assert (await client.post(url, json={"role": "Recruiter"}, headers=h)).status_code == 422
    bad = await client.post(url, json={"linkedin_url": "https://evil.example.com/in/x"}, headers=h)
    assert bad.status_code == 422
    assert (await client.post(url, json={"email": "not-an-email"}, headers=h)).status_code == 422
    unknown = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/api/v1/jobs/{unknown}/contacts", headers=h)).status_code == 404
    assert (await client.delete(f"{url}/{unknown}", headers=h)).status_code == 404


async def test_contacts_written_in_the_description_are_found(client, account):
    await deliver(client, account, LINKEDIN)
    item = await find(client, account, "Chief Engineer")
    h = account["headers"]
    r = await client.post(
        f"/api/v1/jobs/{item['id']}/description",
        json={
            "text": "About the role\nLead platform engineering for our bank.\n"
            "Send your CV to Talent.Team@example-bank.com or reach Priya on "
            "https://in.linkedin.com/in/priya-nair-x/ for questions. Do not write to noreply@example-bank.com.",
            "version": item["version"],
        },
        headers=h,
    )
    assert r.status_code == 200
    url = f"/api/v1/jobs/{item['id']}/contacts"
    found = (await client.get(url, headers=h)).json()["found"]
    assert [(f["kind"], f["value"], f["url"]) for f in found] == [
        ("email", "talent.team@example-bank.com", "mailto:talent.team@example-bank.com"),
        ("linkedin", "priya-nair-x", "https://www.linkedin.com/in/priya-nair-x"),
    ]
    assert found[0]["context"].startswith("Send your CV to")

    # Once saved as a contact, it's listed there instead.
    await client.post(url, json={"email": "talent.team@example-bank.com"}, headers=h)
    after = (await client.get(url, headers=h)).json()
    assert [f["kind"] for f in after["found"]] == ["linkedin"] and len(after["items"]) == 1


# --- Why not 100% ------------------------------------------------------------------------------------


@pytest.mark.nodb
def test_points_lost_add_up_to_the_gap():
    f = {"role": 100, "skills": 50, "loc": 20}
    weights = {"role": 20, "skills": 5, "loc": 10}
    lost = points_lost(f, weights, 60, 70)
    assert sum(lost.values()) == 30
    assert list(lost) == sorted(lost, key=lambda k: -lost[k])
    assert "role" not in lost  # a perfect factor loses nothing
    assert set(lost) == {"similarity", "loc", "skills"}

    capped = points_lost({"role": 90}, {"role": 20}, None, 45)
    assert capped["clash"] == 45 and sum(capped.values()) == 55
    assert points_lost({}, {}, None, 0) == {}


@pytest.mark.nodb
def test_skill_split_keeps_the_jobs_wording():
    job = JobInput("VP", None, None, None, None, None, ["Kafka", "Go", "kafka", " "], "", False)
    resume = ResumeInput("r", "R", "built kafka pipelines", {"aws"}, None)
    assert skill_split(job, resume) == (["Kafka"], ["Go"])


async def test_the_job_says_which_skills_are_missing_and_i_can_add_one(client, account):
    await setup_user(client, account, profile=None)
    await deliver(client, account, INVITE, dkim_domain="naukri.com")
    await run_scoring(account)
    item = await find(client, account, "VP-AI Senior Leader")
    m = (await detail(client, account, item["id"]))["match"]
    assert m["explained"] is True
    assert sum(p["points"] for p in m["points_lost"]) == 100 - m["score"]
    # The skills the invite lists, plus any the description names (as worded by the vocabulary).
    asked = m["skills_have"] + m["skills_missing"]
    assert {"generative ai", "Architect", "Data Science", "Agentic Ai"} <= set(asked)
    assert m["skills_missing"], "the samples should miss at least one of these"

    skill = m["skills_missing"][0]
    r = await client.post(
        f"/api/v1/jobs/{item['id']}/skills", json={"skill": skill}, headers=account["headers"]
    )
    assert r.status_code == 200, r.text
    after = r.json()["match"]
    assert skill in after["skills_have"] and skill not in after["skills_missing"]
    # It went to the match profile of the resume the job was matched with (2026-11-13).
    owner = next(p for p in await match_profiles(client, account) if p["resume_id"] == m["best_resume_id"])
    assert skill in owner["skills"]
    bad = await client.post(
        f"/api/v1/jobs/{item['id']}/skills", json={"skill": "  "}, headers=account["headers"]
    )
    assert bad.status_code == 422


# --- Super admin -------------------------------------------------------------------------------------


async def _admin_headers(client, email: str) -> dict:
    assert "now the super admin" in await set_role(email, "super_admin")
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    client.cookies.clear()
    return auth(r.json()["access_token"])


async def test_only_the_super_admin_changes_the_expiry_days(client, user):
    h = user["headers"]
    assert (await client.get("/api/v1/app-settings", headers=h)).json() == {
        "job_expiry_warn_days": 30,
        "job_expiry_auto_days": 45,
    }
    body = {"job_expiry_warn_days": 14, "job_expiry_auto_days": 21}
    for r in (
        await client.get("/api/v1/admin/settings", headers=h),
        await client.put("/api/v1/admin/settings", json=body, headers=h),
    ):
        assert (r.status_code, r.json()["error"]["code"]) == (403, "forbidden")

    admin = await _admin_headers(client, user["user"]["email"])
    r = await client.put("/api/v1/admin/settings", json=body, headers=admin)
    assert r.status_code == 200 and r.json()["job_expiry_auto_days"] == 21
    assert (await client.get("/api/v1/app-settings", headers=h)).json() == body
    async with sessionmaker()() as db:
        (event,) = await db.scalars(select(AuditEvent).where(AuditEvent.event == "app_settings_changed"))
        assert event.meta["job_expiry_warn_days"] == {"from": 30, "to": 14}

    wrong = await client.put(
        "/api/v1/admin/settings", json={"job_expiry_warn_days": 30, "job_expiry_auto_days": 20}, headers=admin
    )
    assert wrong.status_code == 422
    zero = await client.put(
        "/api/v1/admin/settings", json={"job_expiry_warn_days": 0, "job_expiry_auto_days": 20}, headers=admin
    )
    assert zero.status_code == 422
    # Put the defaults back for the other tests (app_settings isn't truncated between tests).
    await client.put(
        "/api/v1/admin/settings", json={"job_expiry_warn_days": 30, "job_expiry_auto_days": 45}, headers=admin
    )


async def test_the_warning_follows_the_admins_days(client, account):
    await deliver(client, account, LINKEDIN)
    item = await find(client, account, "Chief Engineer")
    await age_job(account, item["id"], 15)
    assert (await detail(client, account, item["id"]))["may_have_expired"] is False

    me = (await client.get("/api/v1/me", headers=account["headers"])).json()
    admin = await _admin_headers(client, me["email"])
    await client.put(
        "/api/v1/admin/settings", json={"job_expiry_warn_days": 14, "job_expiry_auto_days": 45}, headers=admin
    )
    try:
        assert (await detail(client, account, item["id"]))["may_have_expired"] is True
    finally:
        await client.put(
            "/api/v1/admin/settings",
            json={"job_expiry_warn_days": 30, "job_expiry_auto_days": 45},
            headers=admin,
        )


async def test_make_admin_needs_an_existing_account():
    assert (await set_role("nobody@example.com", "admin")).startswith("No account")


async def test_naukris_you_applied_email_marks_the_job_applied_on_that_day(client, account):
    """User feedback 2026-11-15: the job applied to on Naukri is tracked as Applied on the email's date; the
    similar jobs in the email are added as new recommendations."""
    from pathlib import Path

    raw = (
        Path(__file__).parent / "fixtures" / "emails" / "naukri-applied-similar-jobs-2026-11-12.eml"
    ).read_bytes()
    await deliver(client, account, raw, dkim_domain="naukri.com")
    items = (await jobs(client, account, status="all"))["items"]
    assert len(items) == 6
    (applied,) = [j for j in items if j["status"] == "applied"]
    assert applied["job"]["title"] == "Consultant"
    d = await detail(client, account, applied["id"])
    assert d["application"]["applied_on"] == "2026-11-12"
    assert sorted(j["status"] for j in items if j["id"] != applied["id"]) == ["new"] * 5
    apps = (await client.get("/api/v1/applications", headers=account["headers"])).json()
    assert apps["total"] == 1
