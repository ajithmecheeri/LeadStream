"""Milestone 7: LinkedIn connections import, warm paths, the day's suggestions and the outreach tracker."""

import base64
import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import update

from app.core.db import user_scope
from app.modules.networking import notes
from app.modules.networking.companies import company_key, matches
from app.modules.networking.importer import ExportFileError, read_connections
from app.modules.networking.models import Outreach
from app.modules.settings.models import NotificationSettings
from tests.test_jobs import find
from tests.test_matching import run_scoring, setup_user

CSV = (Path(__file__).parent / "fixtures" / "connections" / "Connections.csv").read_bytes()


def upload(data: bytes = CSV, name: str = "Connections.csv", keep_email: bool = False) -> dict:
    return {"file_name": name, "content_base64": base64.b64encode(data).decode(), "keep_email": keep_email}


async def imported(client, account, **kw) -> dict:
    r = await client.post("/api/v1/network/imports", json=upload(**kw), headers=account["headers"])
    assert r.status_code == 201, r.text
    return r.json()


async def daily(client, account, **params) -> dict:
    r = await client.get("/api/v1/network/daily", params=params, headers=account["headers"])
    assert r.status_code == 200, r.text
    return r.json()


async def scored(client, account) -> None:
    await setup_user(client, account)
    await run_scoring(account)


# --- Pure parts --------------------------------------------------------------------------------------


@pytest.mark.nodb
def test_company_keys_ignore_legal_suffixes_and_punctuation():
    assert company_key("Helix Cloud Systems, Inc.") == "helix cloud systems"
    assert company_key("Cyient Limited") == "cyient"
    assert company_key("The Crescendo Global Leadership Hiring India Pvt. Ltd.") == company_key(
        "Crescendo Global Leadership Hiring"
    )
    assert company_key("S&P Global") == "s and p global"
    assert company_key("  ") is None and company_key(None) is None


@pytest.mark.nodb
def test_matching_a_job_company_to_connection_companies():
    keys = {
        "commonwealth bank of australia",
        "crescendo global leadership hiring",
        "bank of baroda",
        "cyient",
    }
    assert matches("Commonwealth Bank", keys) == ["commonwealth bank of australia"]
    assert matches("Crescendo Global Le...", keys) == ["crescendo global leadership hiring"]
    assert matches("Cyient", keys) == ["cyient"]
    assert matches("Bank", keys) == []  # too short to match by words
    assert matches("Crescendo", keys) == ["crescendo global leadership hiring"]  # the same name, fewer words
    assert matches("Global Leadership", keys) == []  # words from the middle never match
    assert matches(None, keys) == []


@pytest.mark.nodb
def test_reading_linkedins_export():
    people, skipped = read_connections("Connections.csv", CSV)
    assert len(people) == 7 and skipped == 1  # one row has no name
    by_name = {p.first_name: p for p in people}
    assert (
        by_name["Arjun"].profile_url == "https://www.linkedin.com/in/arjun-pillai-sample"
    )  # trailing / gone
    assert by_name["Meera"].email is None  # dropped unless asked
    assert by_name["Meera"].connected_on.isoformat() == "2024-03-12"
    assert by_name["Kiran"].person_key == "name:kiran rao (sample)|acme analytics"  # no URL
    assert by_name["Thomas, Jr."].company == "Helix Cloud Systems, Inc."
    kept, _ = read_connections("Connections.csv", CSV, keep_email=True)
    assert {p.first_name: p.email for p in kept}["Meera"] == "meera@example.com"


@pytest.mark.nodb
def test_reading_the_zip_linkedin_emails():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Basic_LinkedInDataExport_11-02-2026/Connections.csv", CSV)
        z.writestr("Basic_LinkedInDataExport_11-02-2026/Profile.csv", "First Name\nX")
    people, _ = read_connections("export.zip", buf.getvalue())
    assert len(people) == 7

    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("Profile.csv", "x")
    with pytest.raises(ExportFileError, match="no Connections.csv"):
        read_connections("export.zip", empty.getvalue())
    with pytest.raises(ExportFileError, match="doesn't look like"):
        read_connections("resume.csv", b"Name,Skill\nA,B\n")


@pytest.mark.nodb
def test_notes_stay_short_and_use_only_profile_facts():
    long_headline = "Engineering leader " * 30
    note = notes.target("Helix Cloud Systems", "VP Engineering", long_headline, "Asha")
    assert len(note) <= notes.INVITE_LIMIT and "Engineering leader" not in note
    assert "A little about me: Cloud leader." in notes.target("Helix", "CTO", "Cloud leader", None)
    assert notes.warm("Meera", "Commonwealth Bank", "Chief Engineer", None, "Asha").startswith("Hi Meera,")
    assert notes.target_role("VP Engineering") == "CTO"
    assert notes.target_role("Director, Technical POM Product Management") == "Chief Product Officer"
    assert notes.target_role("Chief Engineer") == "CEO"
    assert notes.target_role("SEG & India CFO") == "CEO"
    assert notes.target_role("Head S&OP/SIOP") == "Talent Acquisition"
    assert notes.people_search_url("CTO Helix Cloud") == (
        "https://www.linkedin.com/search/results/people/?keywords=CTO%20Helix%20Cloud"
    )


# --- Import ------------------------------------------------------------------------------------------


async def test_import_then_import_again_updates(client, account):
    first = await imported(client, account)
    assert (first["total"], first["added"], first["updated"], first["skipped"]) == (7, 7, 0, 1)

    again = await imported(client, account)
    assert (again["added"], again["updated"]) == (0, 0)
    with_email = await imported(client, account, keep_email=True)
    assert (with_email["updated"], with_email["kept_email"]) == (1, True)

    s = (await client.get("/api/v1/network/summary", headers=account["headers"])).json()
    assert (s["connections"], s["companies"]) == (7, 7)
    assert s["last_import"]["id"] == with_email["id"]

    found = (
        await client.get("/api/v1/network/connections", params={"q": "talent"}, headers=account["headers"])
    ).json()
    assert [c["name"] for c in found["items"]] == ["Meera Shankar (sample)"]
    assert found["items"][0]["email"] == "meera@example.com"


async def test_import_errors(client, account):
    h = account["headers"]
    bad = {"file_name": "x.csv", "content_base64": "not base64!"}
    assert (await client.post("/api/v1/network/imports", json=bad, headers=h)).status_code == 422
    r = await client.post("/api/v1/network/imports", json=upload(b"Name,Skill\nA,B\n"), headers=h)
    assert (r.status_code, r.json()["error"]["code"]) == (422, "not_a_connections_export")
    big = upload(b"x" * (10 * 1024 * 1024 + 1))
    assert (await client.post("/api/v1/network/imports", json=big, headers=h)).status_code == 413
    assert (await client.post("/api/v1/network/imports", json=upload())).status_code == 401


async def test_delete_removes_connections_but_keeps_outreach(client, account):
    await imported(client, account)
    h = account["headers"]
    await client.post("/api/v1/network/outreach", json={"person_name": "Meera"}, headers=h)
    assert (await client.delete("/api/v1/network/connections", headers=h)).status_code == 204
    s = (await client.get("/api/v1/network/summary", headers=h)).json()
    assert (s["connections"], s["last_import"]) == (0, None)
    assert len((await client.get("/api/v1/network/outreach", headers=h)).json()["items"]) == 1


# --- Warm paths --------------------------------------------------------------------------------------


async def test_warm_paths_to_top_matches(client, account):
    await scored(client, account)
    await imported(client, account)
    h = account["headers"]

    paths = (await client.get("/api/v1/network/warm-paths", headers=h)).json()["items"]
    (cba,) = [p for p in paths if p["company"] == "Commonwealth Bank"]
    assert cba["title"] == "Chief Engineer" and cba["total_people"] == 2
    assert [p["name"] for p in cba["people"]][0] == "Meera Shankar (sample)"  # the recruiter first
    assert (await client.get("/api/v1/network/summary", headers=h)).json()["warm_jobs"] == len(paths)

    job = await find(client, account, "Chief Engineer")
    people = (await client.get(f"/api/v1/jobs/{job['id']}/people", headers=h)).json()
    assert people["imported"] is True and len(people["items"]) == 2
    other = await find(client, account, "SEG & India CFO")
    assert (await client.get(f"/api/v1/jobs/{other['id']}/people", headers=h)).json()["items"] == []
    unknown = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/api/v1/jobs/{unknown}/people", headers=h)).status_code == 404


async def test_people_before_any_import(client, account):
    await scored(client, account)
    job = await find(client, account, "Chief Engineer")
    people = (await client.get(f"/api/v1/jobs/{job['id']}/people", headers=account["headers"])).json()
    assert people == {"company": "Commonwealth Bank", "items": [], "imported": False}


# --- Today -------------------------------------------------------------------------------------------


async def test_todays_list_is_built_once_and_capped(client, account):
    await scored(client, account)
    await imported(client, account)

    day = await daily(client, account)
    assert (day["cap"], day["weekly_sent"], day["weekly_limit"]) == (5, 0, 100)
    items = day["items"]
    assert 1 <= len(items) <= 5
    warm = [i for i in items if i["kind"] == "warm"]
    assert (
        warm[0]["name"] == "Meera Shankar (sample)" and warm[0]["company"] == "Commonwealth Bank of Australia"
    )
    assert "Hi Meera," in warm[0]["note"] and warm[0]["job_title"] == "Chief Engineer"
    targets = [i for i in items if i["kind"] == "target"]
    assert targets and all(
        i["search_url"].startswith("https://www.linkedin.com/search/results/people/") for i in targets
    )
    assert all(len(i["note"]) <= notes.INVITE_LIMIT for i in targets)
    assert len({i["company"].lower() for i in items}) == len(items)  # one per company

    assert [i["id"] for i in (await daily(client, account))["items"]] == [i["id"] for i in items]
    rebuilt = await daily(client, account, regenerate="true")
    assert len(rebuilt["items"]) == len(items)


async def test_mark_sent_records_outreach_and_moves_it_along(client, account):
    await scored(client, account)
    await imported(client, account)
    h = account["headers"]
    item = next(i for i in (await daily(client, account))["items"] if i["kind"] == "warm")

    r = await client.post(
        f"/api/v1/network/suggestions/{item['id']}/mark", json={"action": "sent"}, headers=h
    )
    assert r.status_code == 200 and r.json()["status"] == "done"
    again = await client.post(
        f"/api/v1/network/suggestions/{item['id']}/mark", json={"action": "sent"}, headers=h
    )
    assert (again.status_code, again.json()["error"]["code"]) == (409, "already_marked")

    out = (await client.get("/api/v1/network/outreach", headers=h)).json()
    (o,) = out["items"]
    assert (o["person_name"], o["stage"], o["kind"], o["job_title"]) == (
        "Meera Shankar (sample)",
        "sent",
        "warm",
        "Chief Engineer",
    )
    assert out["counts"] == {"sent": 1}
    assert (await daily(client, account))["weekly_sent"] == 1

    url = f"/api/v1/network/outreach/{o['id']}"
    r = await client.patch(url, json={"stage": "accepted", "version": 1}, headers=h)
    r = await client.patch(
        url, json={"stage": "referral", "note": "Referred me to the hiring manager", "version": 2}, headers=h
    )
    assert [(e["kind"], e["stage"]) for e in r.json()["events"]] == [
        ("sent", "sent"),
        ("stage", "accepted"),
        ("stage", "referral"),
    ]
    assert r.json()["note"] == "Referred me to the hiring manager"
    stale = await client.patch(url, json={"stage": "closed", "version": 1}, headers=h)
    assert stale.status_code == 409

    # A rebuilt list doesn't suggest Meera again while that outreach is open.
    rebuilt = await daily(client, account, regenerate="true")
    assert "Meera Shankar (sample)" not in [i["name"] for i in rebuilt["items"] if i["status"] == "open"]


async def test_target_marked_sent_with_the_person_found(client, account):
    await scored(client, account)
    await imported(client, account)
    h = account["headers"]
    item = next(i for i in (await daily(client, account))["items"] if i["kind"] == "target")
    person = {
        "name": "Leela Iyer",
        "title": item["role"],
        "profile_url": "https://www.linkedin.com/in/leela-sample",
    }
    r = await client.post(
        f"/api/v1/network/suggestions/{item['id']}/mark", json={"action": "sent", "person": person}, headers=h
    )
    detail = (await client.get(f"/api/v1/network/outreach/{r.json()['outreach_id']}", headers=h)).json()
    assert (detail["person_name"], detail["kind"], detail["company"]) == (
        "Leela Iyer",
        "target",
        item["company"],
    )


async def test_skipped_and_follow_ups(client, account):
    await scored(client, account)
    await imported(client, account)
    h = account["headers"]
    items = (await daily(client, account))["items"]
    skip, send = items[0], items[1]
    r = await client.post(
        f"/api/v1/network/suggestions/{skip['id']}/mark", json={"action": "skipped"}, headers=h
    )
    assert r.json()["status"] == "skipped"
    sent = await client.post(
        f"/api/v1/network/suggestions/{send['id']}/mark", json={"action": "sent"}, headers=h
    )
    outreach_id = sent.json()["outreach_id"]

    async with user_scope(account["id"]) as db:
        await db.execute(update(Outreach).values(stage_at=datetime.now(UTC) - timedelta(days=8)))
    rebuilt = await daily(client, account, regenerate="true")
    (follow,) = [i for i in rebuilt["items"] if i["kind"] == "followup"]
    assert follow["outreach_id"] == outreach_id and "following up" in follow["note"]
    assert rebuilt["items"][len([i for i in rebuilt["items"] if i["status"] != "open"])]["kind"] == "followup"

    await client.post(f"/api/v1/network/suggestions/{follow['id']}/mark", json={"action": "sent"}, headers=h)
    o = (await client.get(f"/api/v1/network/outreach/{outreach_id}", headers=h)).json()
    assert o["followed_up_at"] is not None and o["events"][-1]["kind"] == "followed_up"


async def test_weekly_limit_stops_new_people(client, account):
    await scored(client, account)
    await imported(client, account)
    async with user_scope(account["id"]) as db:
        await db.execute(update(NotificationSettings).values(network_weekly_limit=0))
    assert (await daily(client, account))["items"] == []


OWN_NOTE = (
    "I came across your profile and was impressed by your leadership experience. I'm a technology leader. "
    "Would be glad to connect and exchange perspectives."
)


async def test_the_users_own_invitation_note_goes_into_todays_find_someone_suggestions(client, account):
    # User feedback 2026-11-11: their own wording for invitations to people they don't know yet.
    await scored(client, account)
    await imported(client, account)
    h = account["headers"]
    first = (await client.get("/api/v1/network/invite-note", headers=h)).json()
    assert first["note"] is None and first["example"].startswith(
        "Hi, I'm interested in the Director of Engineering"
    )

    targets = [i for i in (await daily(client, account))["items"] if i["kind"] == "target"]
    assert targets
    r = await client.put("/api/v1/network/invite-note", json={"note": f"  {OWN_NOTE}\n"}, headers=h)
    assert r.status_code == 200 and r.json()["note"] == OWN_NOTE
    assert r.json()["example"].startswith(OWN_NOTE)
    after = [i for i in (await daily(client, account))["items"] if i["kind"] == "target"]
    assert all(i["note"].startswith(OWN_NOTE) and len(i["note"]) <= notes.INVITE_LIMIT for i in after)
    warm = [i for i in (await daily(client, account))["items"] if i["kind"] == "warm"]
    assert all(OWN_NOTE not in i["note"] for i in warm)  # messages to people you know stay about the job

    back = await client.put("/api/v1/network/invite-note", json={"note": " "}, headers=h)
    assert back.json()["note"] is None
    assert all(not i["note"].startswith(OWN_NOTE) for i in (await daily(client, account))["items"])


async def test_an_invitation_note_over_linkedins_limit_is_refused(client, account):
    r = await client.put("/api/v1/network/invite-note", json={"note": "x" * 301}, headers=account["headers"])
    assert r.status_code == 422
    # A note that fits only without the signature is sent as written.
    assert notes.target("Acme", "CTO", None, "Asha", "y" * 299) == "y" * 299
    assert notes.target("Acme", "CTO", None, "Asha", OWN_NOTE) == f"{OWN_NOTE}\nAsha"


async def test_daily_errors(client, account):
    h = account["headers"]
    future = (datetime.now(UTC) + timedelta(days=3)).date().isoformat()
    assert (await client.get("/api/v1/network/daily", params={"date": future}, headers=h)).status_code == 422
    past = (datetime.now(UTC) - timedelta(days=3)).date().isoformat()
    assert (await daily(client, account, date=past))["items"] == []  # past days are only read, never built
    r = await client.get("/api/v1/network/daily", params={"date": past, "regenerate": "true"}, headers=h)
    assert r.status_code == 422
    unknown = "00000000-0000-0000-0000-000000000000"
    r = await client.post(f"/api/v1/network/suggestions/{unknown}/mark", json={"action": "sent"}, headers=h)
    assert r.status_code == 404
    bad = await client.post(
        f"/api/v1/network/suggestions/{unknown}/mark", json={"action": "liked"}, headers=h
    )
    assert bad.status_code == 422


# --- Outreach recorded by hand -----------------------------------------------------------------------


async def test_manual_outreach(client, account):
    h = account["headers"]
    r = await client.post(
        "/api/v1/network/outreach",
        json={"person_name": "  Neha  Joshi ", "company": "Helix", "note": "Met at a meetup"},
        headers=h,
    )
    assert r.status_code == 201
    assert (r.json()["person_name"], r.json()["kind"], r.json()["stage"]) == ("Neha Joshi", "manual", "sent")
    assert (
        await client.post("/api/v1/network/outreach", json={"person_name": " "}, headers=h)
    ).status_code == 422
    unknown = "00000000-0000-0000-0000-000000000000"
    r = await client.post(
        "/api/v1/network/outreach", json={"person_name": "X", "user_job_id": unknown}, headers=h
    )
    assert r.status_code == 422
    assert (await client.get(f"/api/v1/network/outreach/{unknown}", headers=h)).status_code == 404
    assert (
        await client.patch(
            f"/api/v1/network/outreach/{unknown}", json={"version": 1, "stage": "closed"}, headers=h
        )
    ).status_code == 404
    listed = (await client.get("/api/v1/network/outreach", params={"stage": "closed"}, headers=h)).json()
    assert listed["items"] == [] and listed["counts"] == {"sent": 1}


# --- Companies you applied to (user feedback 2026-11-15) ----------------------------------------------


@pytest.mark.nodb
def test_company_names_for_a_people_search():
    from app.modules.networking.companies import search_name

    assert search_name("GE HealthCare India Pvt. Ltd.") == "GE HealthCare"
    assert search_name("Crescendo Global Le...") == "Crescendo Global"
    assert search_name("Commonwealth Bank") == "Commonwealth Bank"
    assert search_name("  ") is None and search_name(None) is None


@pytest.mark.nodb
def test_people_searches_after_applying_open_linkedin_only_as_links():
    tech = notes.people_searches("Acme", "Director of Engineering")
    assert [(k, label) for k, label, _ in tech] == [
        ("hr", "HR & recruiters"),
        ("leaders", "Leaders"),
        ("hiring_manager", "CTO"),
    ]
    assert all(u.startswith("https://www.linkedin.com/search/results/people/?keywords=") for *_, u in tech)
    assert "%22Acme%22" in tech[0][2] and "engineering%20OR%20technology" in tech[1][2]
    plain = notes.people_searches("Acme", "Accountant")
    assert [k for k, *_ in plain] == ["hr", "leaders"]
    note = notes.applied("Acme", "Director of Engineering", "x" * 400, "Ravi")
    assert (
        len(note) <= notes.INVITE_LIMIT
        and note.startswith("Hi, I recently applied")
        and note.endswith("Ravi")
    )


async def test_companies_you_applied_to_with_searches_and_people_you_know(client, account):
    await scored(client, account)
    await imported(client, account)
    h = account["headers"]
    r = await client.get("/api/v1/network/applied", headers=h)
    assert r.status_code == 200 and r.json() == {"days": 60, "items": []}

    item = await find(client, account, "Chief Engineer")
    r = await client.patch(
        f"/api/v1/jobs/{item['id']}", json={"status": "applied", "version": item["version"]}, headers=h
    )
    assert r.status_code == 200, r.text
    (cba,) = (await client.get("/api/v1/network/applied", headers=h)).json()["items"]
    assert (cba["company"], cba["job_title"], cba["status"]) == (
        "Commonwealth Bank",
        "Chief Engineer",
        "applied",
    )
    assert [s["kind"] for s in cba["searches"]] == ["hr", "leaders", "hiring_manager"]
    assert cba["total_people"] == 2 and cba["people"][0]["name"] == "Meera Shankar (sample)"
    assert "Chief Engineer" in cba["note"] and cba["contacted"] == 0

    r = await client.post(
        "/api/v1/network/outreach",
        json={
            "person_name": "Asha Rao",
            "title": "HR",
            "company": "Commonwealth Bank",
            "user_job_id": item["id"],
        },
        headers=h,
    )
    assert r.status_code == 201
    (cba,) = (await client.get("/api/v1/network/applied", headers=h)).json()["items"]
    assert cba["contacted"] == 1

    # A rejection takes the company off the list.
    detail = (await client.get(f"/api/v1/jobs/{item['id']}", headers=h)).json()["application"]
    r = await client.patch(
        f"/api/v1/applications/{detail['id']}",
        json={"status": "rejected", "version": 1},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert (await client.get("/api/v1/network/applied", headers=h)).json()["items"] == []


async def test_companies_you_applied_to_needs_sign_in(client):
    r = await client.get("/api/v1/network/applied")
    assert r.status_code == 401 and r.json()["error"]["code"]
