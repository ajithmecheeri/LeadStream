"""Google Alerts by RSS (discovery plan decision 10; app/modules/alerts).

The feed is a made-up one in Google's Atom shape (tests/fixtures/google_alerts/feed.xml); fetching is replaced, so
no test reaches Google.
"""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.db import user_scope
from app.modules.alerts import feed, query, service
from app.modules.alerts.router import read_times
from app.modules.alerts.tasks import next_read
from app.modules.catalog.models import Job, JobSource
from app.modules.jobs.models import UserJob
from app.modules.matching.models import JobMatch
from tests.conftest import VALID_PROFILE
from tests.test_ingestion import queued_tasks

FEED = (Path(__file__).parent / "fixtures" / "google_alerts" / "feed.xml").read_bytes()
FEED_URL = "https://www.google.com/alerts/feeds/01234567890123456789/11111111111111111111"


# --- The feed (no database) ------------------------------------------------------------------------------


@pytest.mark.nodb
def test_the_feed_link_is_googles_alert_feed_only():
    assert (
        feed.feed_url("  http://google.com/alerts/feeds/01234567890123456789/11111111111111111111/ ")
        == FEED_URL
    )
    for bad in (
        "https://www.google.com/alerts",
        "https://www.google.com.evil.io/alerts/feeds/0123456789/0123456789",
        "https://evil.com/alerts/feeds/0123456789/0123456789",
        "file:///etc/passwd",
        "https://www.google.com/url?url=https://evil.com",
    ):
        with pytest.raises(feed.NotAFeed):
            feed.feed_url(bad)


@pytest.mark.nodb
def test_the_feed_gives_portal_jobs_and_counts_the_other_links():
    parsed = feed.parse(FEED)
    assert parsed.query.startswith('"VP Engineering" (Bengaluru OR Bangalore) (site:linkedin.com/jobs/view')
    assert (
        parsed.entries[0].link == "https://in.linkedin.com/jobs/view/vp-engineering-at-acme-cloud-4012345678"
    )
    got = feed.cards(parsed)
    assert got.other_links == 2  # a company careers page and a LinkedIn search page
    by_id = {c.source_job_id: c for c in got.cards}
    assert len(got.cards) == 4  # the Acme job twice in the feed is one card
    acme = by_id["4012345678"]
    assert (acme.source, acme.title, acme.company) == ("linkedin", "VP Engineering", "Acme Cloud")
    assert acme.location.startswith("Bengaluru")
    assert acme.canonical_url == "https://www.linkedin.com/jobs/view/4012345678/"
    assert acme.details["Google snippet"].startswith("Acme Cloud is hiring a VP Engineering")
    assert "&amp;" not in acme.details["Google snippet"] and "<b>" not in acme.details["Google snippet"]
    assert acme.description is None and acme.lead == "job_board"
    globex = by_id["4023456789"]  # Google's title says nothing: read from the link
    assert (globex.title, globex.company) == ("Head of Platform Engineering", "Globex")
    initech = by_id["140525901234"]
    assert (initech.source, initech.title, initech.company) == (
        "naukri",
        "Vice President - Engineering",
        "Initech",
    )
    umbrella = by_id["58167202"]
    assert (umbrella.source, umbrella.title, umbrella.company) == (
        "foundit",
        "Director Engineering",
        "Umbrella Corp",
    )


@pytest.mark.nodb
@pytest.mark.parametrize(
    "body",
    [
        b"not xml",
        b"<rss><channel/></rss>",
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><feed xmlns="http://www.w3.org/2005/Atom"/>',
    ],
)
def test_anything_else_is_not_a_feed(body):
    with pytest.raises(feed.NotAFeed):
        feed.parse(body)


@pytest.mark.nodb
def test_one_suggested_alert_covers_the_three_portals():
    q = service.alert_query("VP Engineering", "Bengaluru")
    assert q == (
        '"VP Engineering" ("Bengaluru" OR "Bangalore") '
        "(site:linkedin.com/jobs/view OR site:naukri.com/job-listings OR site:foundit.in/job)"
    )
    own = service.alert_query(
        '("Technology Director" OR "Engineering Director") ("Bengaluru" OR "Bangalore")', None
    )
    assert own.startswith(
        '("Technology Director" OR "Engineering Director") ("Bengaluru" OR "Bangalore") (site:'
    )
    assert service.create_link(q).startswith("https://www.google.com/alerts?q=%22VP%20Engineering%22")
    assert service.same_query(q.upper(), "  " + q)


@pytest.mark.nodb
def test_feeds_are_read_three_times_a_day_on_the_users_clock():
    now = datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
    assert next_read(now) == datetime(2026, 11, 15, 14, 30, tzinfo=UTC)
    assert next_read(datetime(2026, 11, 15, 20, 0, tzinfo=UTC)) == datetime(2026, 11, 16, 2, 30, tzinfo=UTC)
    assert read_times("Asia/Kolkata", now) == "08:00, 14:00 and 20:00 IST"


# --- The endpoints and the read -------------------------------------------------------------------------------


@pytest.fixture
def google(monkeypatch):
    calls: list[str] = []

    async def fetch(url):
        calls.append(url)
        return FEED

    monkeypatch.setattr(service, "fetch", fetch)
    return calls


async def test_suggested_alerts_come_from_the_users_roles_and_places(client, account):
    await client.post("/api/v1/profiles", headers=account["headers"], json=VALID_PROFILE)
    r = await client.get("/api/v1/alerts", headers=account["headers"])
    assert r.status_code == 200
    body = r.json()
    pairs = {(s["role"], s["place"]) for s in body["suggestions"]}
    assert pairs == {
        (role, place) for role in VALID_PROFILE["target_roles"] for place in ("Bengaluru", "Remote")
    }
    assert all(s["create_url"].startswith("https://www.google.com/alerts?q=") for s in body["suggestions"])
    assert not any(s["added"] for s in body["suggestions"]) and body["feeds"] == []
    assert (await client.get("/api/v1/alerts")).status_code == 401


async def test_a_feed_is_added_read_and_its_jobs_scored(client, account, google):
    h = account["headers"]
    r = await client.post("/api/v1/alerts", headers=h, json={"feed_url": FEED_URL + "/"})
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    assert [t["task_name"] for t in await queued_tasks() if t["task_name"] == "alerts.read_feed"] == [
        "alerts.read_feed"
    ]

    assert await service.read(account["id"], UUID(fid)) == 4
    assert google == [FEED_URL]
    async with user_scope(account["id"]) as db:
        jobs = list(await db.scalars(select(UserJob)))
        sources = {s.source for s in await db.scalars(select(JobSource))}
        catalog = list(await db.scalars(select(Job)))
    assert len(jobs) == 4 and {j.lead for j in jobs} == {"job_board"}
    assert sources == {"linkedin", "naukri", "foundit"}
    assert all(j.verified is False for j in catalog)
    scoring = [t for t in await queued_tasks() if "google alerts" in str(t["args"])]
    assert len(scoring) == 1 and scoring[0]["task_name"] == "matching.score"

    # Read again: nothing new, the same four jobs.
    assert await service.read(account["id"], UUID(fid)) == 0
    async with user_scope(account["id"]) as db:
        assert len(list(await db.scalars(select(UserJob)))) == 4
        db.add(JobMatch(user_job_id=jobs[0].id, user_id=account["id"], band="strong", score=90))

    body = (await client.get("/api/v1/alerts", headers=h)).json()
    (f,) = body["feeds"]
    assert f["query"].startswith('"VP Engineering"') and f["last_error"] is None
    assert (f["found"], f["added"], f["skipped"], f["top_matches"]) == (4, 0, 2, 1)

    dup = await client.post("/api/v1/alerts", headers=h, json={"feed_url": FEED_URL})
    assert dup.status_code == 409
    assert (await client.delete(f"/api/v1/alerts/{fid}", headers=h)).status_code == 204
    assert (await client.delete(f"/api/v1/alerts/{fid}", headers=h)).status_code == 404
    async with user_scope(account["id"]) as db:  # the jobs it brought stay
        assert len(list(await db.scalars(select(UserJob)))) == 4


async def test_a_feed_link_must_be_googles_and_a_failed_read_is_shown(client, account, monkeypatch):
    h = account["headers"]
    bad = await client.post(
        "/api/v1/alerts", headers=h, json={"feed_url": "https://evil.com/alerts/feeds/1/2"}
    )
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "not_a_feed"
    assert bad.json()["error"]["details"][0]["field"] == "feed_url"

    async def gone(url):
        raise service.FetchError("Google says this feed no longer exists")

    monkeypatch.setattr(service, "fetch", gone)
    fid = (await client.post("/api/v1/alerts", headers=h, json={"feed_url": FEED_URL})).json()["id"]
    assert await service.read(account["id"], UUID(fid)) == 0
    (f,) = (await client.get("/api/v1/alerts", headers=h)).json()["feeds"]
    assert f["last_error"].startswith("Google says") and f["last_read_at"] is not None
    assert (await client.post("/api/v1/alerts", json={"feed_url": FEED_URL})).status_code == 401


async def test_up_to_five_alert_roles_can_be_set_and_reset(client, account):
    h = account["headers"]
    await client.post("/api/v1/profiles", headers=h, json=VALID_PROFILE)
    body = (await client.get("/api/v1/alerts", headers=h)).json()
    assert body["roles_custom"] is False and body["roles"] == VALID_PROFILE["target_roles"][:5]

    roles = ["Head of Engineering", "VP Engineering", ' "CTO" ', "vp engineering", "Director of Platform"]
    r = await client.put("/api/v1/alerts/roles", headers=h, json={"roles": roles})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["roles_custom"] is True
    assert body["roles"] == ['"Head of Engineering"', '"VP Engineering"', '"CTO"', '"Director of Platform"']
    assert {s["role"] for s in body["suggestions"]} == set(body["roles"])
    assert {s["place"] for s in body["suggestions"]} == {"Bengaluru", "Remote"}

    six = await client.put("/api/v1/alerts/roles", headers=h, json={"roles": [f"Role {i}" for i in range(6)]})
    assert six.status_code == 422
    short = await client.put("/api/v1/alerts/roles", headers=h, json={"roles": ["X"]})
    assert short.status_code == 422

    back = (await client.put("/api/v1/alerts/roles", headers=h, json={"roles": []})).json()
    assert back["roles_custom"] is False and back["roles"] == VALID_PROFILE["target_roles"][:5]
    assert (await client.put("/api/v1/alerts/roles", json={"roles": []})).status_code == 401


@pytest.mark.nodb
@pytest.mark.parametrize(
    ("typed", "saved"),
    [
        (
            "(Technology Director OR Engineering Director) (Bengaluru OR Bangalore)",
            '("Technology Director" OR "Engineering Director") ("Bengaluru" OR "Bangalore")',
        ),
        ("VP Engineering", '"VP Engineering"'),
        ("VP Engineering OR Head of Engineering", '("VP Engineering" OR "Head of Engineering")'),
        ("Director (Technology | Engineering)", '"Director" ("Technology" OR "Engineering")'),
        ('  ("CTO"   OR  "Chief Technology Officer")  ', '("CTO" OR "Chief Technology Officer")'),
        # Saved once, saved again: the same.
        (
            '("Technology Director" OR "Engineering Director") ("Bengaluru" OR "Bangalore")',
            '("Technology Director" OR "Engineering Director") ("Bengaluru" OR "Bangalore")',
        ),
    ],
)
def test_a_role_is_saved_in_googles_syntax(typed, saved):
    assert query.google_terms(typed) == saved


@pytest.mark.nodb
@pytest.mark.parametrize("bad", ["(VP Engineering", "VP Engineering)", "((A OR B) C)", "()"])
def test_brackets_must_be_balanced_and_flat(bad):
    with pytest.raises(query.BadQuery):
        query.google_terms(bad)


async def test_a_role_that_names_its_city_gets_one_alert(client, account):
    """Sign-up said Bengaluru; the role names it (as Bangalore too): no second city is added."""
    h = account["headers"]
    typed = "(Technology Director OR Engineering Director) (Bengaluru OR Bangalore)"
    r = await client.put("/api/v1/alerts/roles", headers=h, json={"roles": [typed, "VP Engineering"]})
    assert r.status_code == 200, r.text
    body = r.json()
    saved = '("Technology Director" OR "Engineering Director") ("Bengaluru" OR "Bangalore")'
    assert body["roles"] == [saved, '"VP Engineering"']
    by_role = {}
    for s in body["suggestions"]:
        by_role.setdefault(s["role"], []).append(s)
    (own,) = by_role[saved]
    assert own["place"] is None and own["query"].startswith(saved + " (site:linkedin.com/jobs/view")
    (vp,) = by_role['"VP Engineering"']
    assert vp["place"] == "Bengaluru" and vp["query"].startswith(
        '"VP Engineering" ("Bengaluru" OR "Bangalore")'
    )
    bad = await client.put("/api/v1/alerts/roles", headers=h, json={"roles": ["(VP Engineering"]})
    assert bad.status_code == 422 and "bracket" in r.text.lower() + bad.text.lower()
