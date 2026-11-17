"""Job sources through the Job Search Service (docs/plan-jobsearch-build.md): following employers, checking
them, the event feed, what reaches each user, the demand sent, and the old feeds' export.

The service is replaced by FakeJobSearch (same methods as sources.client.JobSearch); the service's own tests are
in services/jobsearch/tests.
"""

import json
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.core.db import sessionmaker, user_scope
from app.modules.catalog.models import Job
from app.modules.jobs.models import UserJob
from app.modules.matching.models import JobMatch
from app.modules.sources import client, sync
from app.modules.sources.models import CompanyFeed, JobSearchSync, PlatformCompany, SourceRun
from tests.conftest import VALID_PROFILE, admin_account, auth, signup
from tests.test_ingestion import queued_tasks

BOARD_URL = {"greenhouse": "https://boards.greenhouse.io/{}", "lever": "https://jobs.lever.co/{}"}
SUGGESTED = [
    ("Okta", "greenhouse", "okta"),
    ("Meesho", "lever", "meesho"),
    ("NVIDIA", "workday", "nv.wd5.myworkdayjobs.com/nv/Ext"),
]
# Like the Greenhouse sample of milestone 9: four India jobs at Acme Cloud.
ACME_JOBS = [
    ("7001", "Director of Engineering, Platform", "Bengaluru, India"),
    ("7002", "Principal Engineer", "Remote - India"),
    ("7004", "Software Engineer II", "Bengaluru, India"),
    ("7005", "Director, Finance", "Bengaluru, India"),
]


class FakeJobSearch:
    """An in-memory Job Search Service."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.feed: list[dict] = []
        self.checks: list[str] = []
        self.demand: list[dict] | None = None
        self.up = True
        self.adzuna = False
        self.check_result: dict[str, dict | None] = {}
        self.last_check: dict[str, str] = {}  # employer → its board's last run start

    def _guard(self):
        if not self.up:
            raise client.Unavailable("ConnectError")

    async def register(self, *, name=None, system=None, board=None, url=None, employer_id=None):
        self._guard()
        if url and "linkedin.com" in url:
            raise client.Refused(
                400, "job_portal", "BrewMyJob never reads job portals such as LinkedIn or Naukri"
            )
        if url:
            m = re.match(r"https://([a-z0-9]+)\.wd5\.myworkdayjobs\.com/([A-Za-z]+)", url)
            if not m:
                raise client.Refused(400, "unknown_board", "That link isn't a job board we can read")
            system, board = "workday", f"{m[1]}.wd5.myworkdayjobs.com/{m[1]}/{m[2]}"
        for e in self.rows.values():
            if (e["system"], e["board"].lower()) == (system, board.lower()):
                return e
        eid = str(employer_id or uuid4())
        self.rows[eid] = {
            "id": eid,
            "name": name or board,
            "system": system,
            "board": board,
            "board_url": BOARD_URL.get(system, "https://{}").format(board),
            "last_checked_at": None,
            "last_error": None,
            "jobs_total": None,
            "jobs_in_scope": None,
            "last_run": None,
        }
        return self.rows[eid]

    async def lookup(self, query):
        self._guard()
        return [
            {
                "system": "lever",
                "board": "acme",
                "board_url": "https://jobs.lever.co/acme",
                "in_scope": 3,
                "total": 10,
                "sample": ["VP Engineering"],
            }
        ]

    async def employers(self, ids):
        self._guard()
        return [self.rows[str(i)] for i in ids if str(i) in self.rows]

    async def suggested(self):
        self._guard()
        return [{"name": n, "system": s, "board": b, "board_url": "https://x"} for n, s, b in SUGGESTED]

    async def check(self, employer_id):
        self._guard()
        self.checks.append(str(employer_id))
        e = self.rows[str(employer_id)]
        if e["board"] == "gone":
            e["last_error"] = "No job board 'gone' on Greenhouse any more"
            return {"found": 0, "new": 0, "error": e["last_error"]}
        return self.check_result.get(e["board"], {"found": 4, "new": 0, "error": None})

    async def listings(self, employer_id):
        self._guard()
        eid = str(employer_id)
        if eid not in self.rows:
            raise client.Refused(404, "not_found", "Employer not found")
        latest: dict[str, dict] = {}
        for e in self.feed:
            if e["listing"]["employer_id"] == eid:
                latest[e["listing"]["listing_id"]] = {**e["listing"], "description": None}
        started = self.last_check.get(eid)
        return {
            "employer_id": eid,
            "last_run": {"started_at": started, "finished_at": started} if started else None,
            "listings": [x for x in latest.values() if x["status"] == "active"],
        }

    async def events(self, after, limit=500):
        self._guard()
        page = [e for e in self.feed if e["event_id"] > after][:limit]
        return {"events": page, "next_cursor": page[-1]["event_id"] if page else after}

    async def put_demand(self, areas):
        self._guard()
        self.demand = areas
        return {"active": len(areas)}

    async def sources(self):
        self._guard()
        return [
            {
                "connector": "greenhouse",
                "configured": True,
                "boards": len(self.rows),
                "last_run_at": None,
                "runs_24h": 0,
                "failures_24h": 0,
                "last_error": None,
            },
            {
                "connector": "adzuna",
                "configured": self.adzuna,
                "boards": 0,
                "last_run_at": None,
                "runs_24h": 0,
                "failures_24h": 0,
                "last_error": None,
            },
        ]

    # --- test helpers ---

    def publish(
        self, kind: str, employer_id: str | None, job_id: str, title: str, location: str, **kw
    ) -> str:
        """Add an event for a listing (the same job_id is the same listing)."""
        listing_id = next(
            (
                e["listing"]["listing_id"]
                for e in self.feed
                if e["listing"]["sources"][0]["source_job_id"] == job_id
            ),
            str(uuid4()),
        )
        source = kw.pop("source", "greenhouse" if employer_id else "adzuna")
        company = kw.pop("company", self.rows[employer_id]["name"] if employer_id else "Nimbus Tech")
        listing = {
            "listing_id": listing_id,
            "employer_id": employer_id,
            "company": company,
            "title": title,
            "location": location,
            "work_model": None,
            "experience": None,
            "salary": None,
            "description": kw.pop("description", f"{title} at {company}."),
            "skills": [],
            "details": {},
            "posted_at": "2026-11-10T00:00:00+00:00",
            "first_seen_at": kw.pop("first_seen_at", "2026-11-14T00:00:00+00:00"),
            "last_seen_at": "2026-11-14T00:00:00+00:00",
            "closed_at": kw.pop("closed_at", None),
            "status": kw.pop("status", "active"),
            "sources": [
                {
                    "source": source,
                    "source_job_id": job_id,
                    "url": f"https://jobs.example/{job_id}",
                    "apply_url": None,
                }
            ],
            "requisition_id": None,
            "content_hash": "h",
            "version": 1,
        }
        self.feed.append(
            {
                "event_id": len(self.feed) + 1,
                "type": kind,
                "occurred_at": "2026-11-14T00:00:00+00:00",
                "listing": listing,
            }
        )
        return listing_id

    def publish_acme(self, employer_id: str) -> None:
        for job_id, title, location in ACME_JOBS:
            self.publish("NEW", employer_id, job_id, title, location)


@pytest.fixture
def service(monkeypatch) -> FakeJobSearch:
    fake = FakeJobSearch()

    @asynccontextmanager
    async def connect():
        yield fake

    monkeypatch.setattr(client, "connect", connect)
    return fake


@pytest.fixture
async def account(client) -> dict:
    """Job sources is for admins (user, 2026-11-17): the accounts that follow companies here are admins."""
    return await admin_account(client)


@pytest.fixture
async def user(client) -> dict:
    return await admin_account(client)


async def follow(client_, account, name="Acme Cloud", board="acmecloud", ats="greenhouse") -> str:
    r = await client_.post(
        "/api/v1/sources/companies",
        headers=account["headers"],
        json={"name": name, "ats": ats, "board": board},
    )
    assert r.status_code == 202, r.text
    return r.json()["id"]


async def my_jobs(user_id) -> list[UserJob]:
    async with user_scope(user_id) as db:
        return list(await db.scalars(select(UserJob).order_by(UserJob.first_seen_at)))


async def page(client_, account) -> dict:
    r = await client_.get("/api/v1/sources", headers=account["headers"])
    assert r.status_code == 200, r.text
    return r.json()


async def test_following_a_company_registers_it_and_queues_its_check(client, account, service):
    eid = await follow(client, account)
    (task,) = await queued_tasks()
    assert task["task_name"] == "sources.refresh_user" and json.loads(task["args"])["employer_ids"] == [eid]
    sources = await page(client, account)
    (company,) = sources["companies"]
    assert (company["id"], company["name"], company["board_url"]) == (
        eid,
        "Acme Cloud",
        "https://boards.greenhouse.io/acmecloud",
    )
    assert (
        company["last_run"] is None and sources["checking"] is True and sources["service_available"] is True
    )
    assert sources["last_check"] is None and sources["check_times"].startswith("every 3 hours (next at ")
    assert sources["last_run"] is None


async def test_a_check_brings_the_relevant_jobs_from_the_event_feed(client, account, service):
    await client.post("/api/v1/profiles", headers=account["headers"], json=VALID_PROFILE)
    eid = await follow(client, account)
    service.publish_acme(eid)
    service.check_result["acmecloud"] = {"found": 4, "new": 4, "error": None}

    async with client_ctx(service) as js:
        summary = await sync.check_user(js, account["id"])

    # Kept: Director of Engineering, Principal Engineer (remote India). Left out: Software Engineer II (below
    # the profile's level), Director, Finance (another field).
    assert service.checks == [eid] and summary.events == 4 and summary.added[account["id"]] == 2
    jobs = await my_jobs(account["id"])
    assert {j.lead for j in jobs} == {"company_feed"} and len(jobs) == 2
    scoring = [t for t in await queued_tasks() if "job search service" in str(t["args"])]
    assert len(scoring) == 1 and scoring[0]["task_name"] == "matching.score"

    sources = await page(client, account)
    (company,) = sources["companies"]
    assert company["my_jobs"] == 2
    assert (
        company["last_run"]["found"] == 4
        and company["last_run"]["added"] == 2
        and company["last_run"]["skipped"] == 2
    )
    last = sources["last_check"]
    assert (last["sources"], last["found"], last["added"], last["skipped"], last["errors"]) == (1, 4, 2, 2, 0)

    # Pulled again: the cursor moved on, nothing comes twice.
    async with client_ctx(service) as js:
        again = await sync.pull(js)
    assert again.events == 0 and len(await my_jobs(account["id"])) == 2
    # The last run that brought jobs: 4 pulled, all new to BrewMyJob; 2 fit this user; not scored yet.
    run = (await page(client, account))["last_run"]
    assert (run["jobs"], run["new"], run["updated"], run["closed"]) == (4, 4, 0, 0)
    assert (run["fit"], run["added"], run["top_matches"]) == (2, 2, 0)
    async with user_scope(account["id"]) as db:
        db.add(JobMatch(user_job_id=jobs[0].id, user_id=account["id"], band="strong", score=91))
    assert (await page(client, account))["last_run"]["top_matches"] == 1


@asynccontextmanager
async def client_ctx(fake):
    yield fake


async def test_a_board_that_is_gone_is_reported_not_raised(client, account, service):
    eid = await follow(client, account, "Gone Inc", "gone")
    async with client_ctx(service) as js:
        await sync.check_user(js, account["id"])
    (company,) = (await page(client, account))["companies"]
    assert company["id"] == eid and company["last_error"] == "No job board 'gone' on Greenhouse any more"
    assert company["last_run"]["error"] == company["last_error"]


async def test_one_read_serves_every_follower(client, account, user, service):
    """The service reads each board once; the event reaches everyone who follows the employer."""
    eid = await follow(client, account)
    assert await follow(client, user, name="Acme", board="AcmeCloud") == eid  # one employer for both
    service.publish_acme(eid)
    async with client_ctx(service) as js:
        await sync.pull(js)
    other = UUID((await client.get("/api/v1/me", headers=user["headers"])).json()["id"])
    assert len(await my_jobs(account["id"])) == 4 and len(await my_jobs(other)) == 4  # no profiles: all kept


async def test_joining_later_brings_the_open_jobs_that_fit(client, account, service):
    """2026-11-16: jobs open before you followed a company never reached you (the feed brings only changes).
    2026-11-17: with one shared list, a job seeker who joins later gets every company's open jobs that fit when
    their first Skill Match profile is made: the ones that fit, once, and the rest listed in From sources."""
    eid = await follow(client, account)
    service.publish_acme(eid)
    async with client_ctx(service) as js:
        await sync.pull(js)
    seeker = await signup(client)  # joins after the jobs were pulled
    client.cookies.clear()
    h = auth(seeker["access_token"])
    other = UUID(seeker["user"]["id"])
    await client.post("/api/v1/profiles", headers=h, json=VALID_PROFILE)
    assert await my_jobs(other) == []
    async with client_ctx(service) as js:
        assert await sync.catch_up_all(js, other) == 2
    titles = sorted(await db_titles(other))
    assert titles == ["Director of Engineering, Platform", "Principal Engineer"]  # left out: junior, finance
    out = (await client.get("/api/v1/sources/jobs", headers=h)).json()
    assert (out["total"], out["in_list"], out["left_out"]) == (4, 2, 2)
    async with client_ctx(service) as js:
        assert await sync.catch_up_all(js, other) == 0
    assert len(await my_jobs(other)) == 2


async def test_a_new_company_is_caught_up_for_job_seekers_with_profiles(client, account, service):
    """An admin adds a company: its open jobs that fit reach every job seeker who has a search profile."""
    seeker = await signup(client)
    client.cookies.clear()
    other = UUID(seeker["user"]["id"])
    await client.post("/api/v1/profiles", headers=auth(seeker["access_token"]), json=VALID_PROFILE)
    eid = await follow(client, account)
    service.publish_acme(eid)
    async with client_ctx(service) as js:
        await sync.pull(js)  # the jobs reach everyone already (the shared list): catch-up adds nothing twice
        summary = await sync.check_user(js, account["id"], [UUID(eid)])
    assert summary.added.get(other, 0) == 0
    assert sorted(await db_titles(other)) == ["Director of Engineering, Platform", "Principal Engineer"]


async def db_titles(user_id) -> list[str]:
    async with user_scope(user_id) as db:
        return list(await db.scalars(select(Job.title).join(UserJob, UserJob.job_id == Job.id)))


async def test_an_employer_nobody_follows_reaches_nobody(client, account, service):
    other = await service.register(name="Other", system="greenhouse", board="other")
    service.publish("NEW", other["id"], "9001", "Director of Engineering", "Bengaluru, India")
    async with client_ctx(service) as js:
        summary = await sync.pull(js)
    assert summary.stored == 1 and await my_jobs(account["id"]) == []
    async with sessionmaker()() as db:
        assert await db.scalar(select(Job.title)) == "Director of Engineering"  # in the shared catalog anyway


async def test_job_api_listings_reach_users_whose_profiles_they_pass(client, account, user, service):
    await client.post("/api/v1/profiles", headers=account["headers"], json=VALID_PROFILE)
    service.publish("NEW", None, "az-1", "VP Engineering", "Bengaluru, Karnataka")
    service.publish("NEW", None, "az-2", "Data Entry Operator", "Bengaluru, Karnataka")
    async with client_ctx(service) as js:
        await sync.pull(js)
    (job,) = await my_jobs(account["id"])
    assert job.lead == "job_board"
    other = UUID((await client.get("/api/v1/me", headers=user["headers"])).json()["id"])
    assert await my_jobs(other) == []  # no search profiles: no job-API jobs
    run = (await page(client, account))["adzuna"]["last_run"]
    assert run["found"] == 2 and run["added"] == 1


async def test_an_updated_listing_refreshes_the_catalog_and_is_rescored(client, account, service):
    eid = await follow(client, account)
    service.publish(
        "NEW", eid, "7001", "Director of Engineering", "Bengaluru, India", description="Old text."
    )
    async with client_ctx(service) as js:
        await sync.pull(js)
    service.publish(
        "UPDATED", eid, "7001", "Director of Engineering", "Bengaluru, India", description="New text."
    )
    async with client_ctx(service) as js:
        await sync.pull(js)
    async with sessionmaker()() as db:
        assert await db.scalar(select(Job.description)) == "New text."
    (uj,) = await my_jobs(account["id"])
    rescored = [
        t for t in await queued_tasks() if t["task_name"] == "matching.score" and str(uj.id) in str(t["args"])
    ]
    assert len(rescored) == 2  # once when it arrived, once when it changed


async def test_a_listing_new_and_closed_in_one_pull_only_counts_as_closed(client, account, service):
    eid = await follow(client, account)
    service.publish("NEW", eid, "7001", "Director of Engineering", "Bengaluru, India")
    service.publish(
        "CLOSED",
        eid,
        "7001",
        "Director of Engineering",
        "Bengaluru, India",
        status="closed",
        closed_at="2026-11-14T03:00:00+00:00",
    )
    async with client_ctx(service) as js:
        summary = await sync.pull(js)
    assert (summary.closed, summary.stored) == (1, 0) and await my_jobs(account["id"]) == []


async def test_following_suggested_companies(client, account, service):
    r = await client.post(
        "/api/v1/sources/companies/suggested",
        headers=account["headers"],
        json={"boards": ["greenhouse:okta", "lever:meesho", "nope:x"]},
    )
    assert r.status_code == 202 and len(r.json()["ids"]) == 2
    sources = await page(client, account)
    assert [c["name"] for c in sources["companies"]] == ["Meesho", "Okta"]
    assert {s["name"] for s in sources["suggestions"] if s["watching"]} == {"Okta", "Meesho"}
    r = await client.post(
        "/api/v1/sources/companies/suggested", headers=account["headers"], json={"boards": ["x:y"]}
    )
    assert r.status_code == 404


async def test_a_workday_careers_link_can_be_followed(client, account, service):
    r = await client.post(
        "/api/v1/sources/companies",
        headers=account["headers"],
        json={"name": "NVIDIA", "url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"},
    )
    assert r.status_code == 202
    (company,) = (await page(client, account))["companies"]
    assert company["ats"] == "workday" and company["name"] == "NVIDIA"
    bad = await client.post(
        "/api/v1/sources/companies",
        headers=account["headers"],
        json={"name": "X", "url": "https://x.example/jobs"},
    )
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "unknown_board"


async def test_unfollowing_keeps_the_jobs(client, account, service):
    eid = await follow(client, account)
    service.publish_acme(eid)
    async with client_ctx(service) as js:
        await sync.pull(js)
    r = await client.delete(f"/api/v1/sources/companies/{eid}", headers=account["headers"])
    assert r.status_code == 204
    assert (await page(client, account))["companies"] == []
    assert len(await my_jobs(account["id"])) == 4
    again = await client.delete(f"/api/v1/sources/companies/{eid}", headers=account["headers"])
    assert again.status_code == 404


async def test_invalid_companies_are_refused(client, account, service):
    for body in (
        {"name": "X", "ats": "greenhouse", "board": "../etc/passwd"},
        {"name": "X", "ats": "bamboo", "board": "x"},
        {"name": "X"},
    ):
        r = await client.post("/api/v1/sources/companies", headers=account["headers"], json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", body


async def test_check_now_waits_ten_minutes_between_checks(client, account, service):
    r = await client.post("/api/v1/sources/check", headers=account["headers"])
    assert r.status_code == 202
    await follow(client, account)
    async with client_ctx(service) as js:
        await sync.check_user(js, account["id"])
    r = await client.post("/api/v1/sources/check", headers=account["headers"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "checked_recently"


async def test_lookup_returns_the_boards_found(client, account, service):
    r = await client.post("/api/v1/sources/lookup", headers=account["headers"], json={"query": "Acme"})
    assert r.status_code == 200
    assert r.json() == [
        {
            "ats": "lever",
            "board": "acme",
            "board_url": "https://jobs.lever.co/acme",
            "india": 3,
            "total": 10,
            "sample": ["VP Engineering"],
        }
    ]
    r = await client.post("/api/v1/sources/lookup", headers=account["headers"], json={"query": "x"})
    assert r.status_code == 422


async def test_when_the_service_is_down_the_page_still_loads(client, account, service):
    eid = await follow(client, account)
    service.up = False
    sources = await page(client, account)
    assert sources["service_available"] is False
    (company,) = sources["companies"]
    assert company["id"] == eid and company["name"] == "Acme Cloud" and company["board_url"] is None
    r = await client.post("/api/v1/sources/lookup", headers=account["headers"], json={"query": "Acme"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "jobsearch_unavailable"
    r = await client.post(
        "/api/v1/sources/companies",
        headers=account["headers"],
        json={"name": "B", "ats": "lever", "board": "b"},
    )
    assert r.status_code == 503


async def test_adzuna_shows_the_users_searches(client, account, service):
    await client.post("/api/v1/profiles", headers=account["headers"], json=VALID_PROFILE)
    adz = (await page(client, account))["adzuna"]
    assert adz["configured"] is False and adz["searches"][0] == "VP Engineering in Bengaluru"
    service.adzuna = True
    assert (await page(client, account))["adzuna"]["configured"] is True


async def test_source_runs_are_private(client, account, user, service):
    eid = await follow(client, account)
    service.publish_acme(eid)
    async with client_ctx(service) as js:
        await sync.pull(js)
    async with user_scope(account["id"]) as db:
        assert len(list(await db.scalars(select(SourceRun)))) == 1
    # The companies are one shared list (2026-11-17); each user's run lines stay their own.
    sources = await page(client, user)
    assert [c["id"] for c in sources["companies"]] == [eid] and sources["checking"] is False


async def test_a_junior_user_gets_the_junior_jobs(client, user, service):
    """The relevance check is per user: someone early in their career sees the junior openings too."""
    junior = {
        **VALID_PROFILE,
        "name": "Engineer",
        "target_roles": ["Software Engineer"],
        "min_seniority": 1,
        "locations": ["Hyderabad", "Bengaluru", "Remote"],
    }
    await client.post("/api/v1/profiles", headers=user["headers"], json=junior)
    eid = await follow(client, user)
    service.publish_acme(eid)
    async with client_ctx(service) as js:
        summary = await sync.pull(js)
    assert (
        sum(summary.added.values()) == 3
    )  # Director of Engineering, Principal Engineer, Software Engineer II


async def test_the_demand_is_aggregated_and_sent_when_it_changes(client, account, user, service):
    await client.post("/api/v1/profiles", headers=account["headers"], json=VALID_PROFILE)
    await client.post(
        "/api/v1/profiles", headers=user["headers"], json={**VALID_PROFILE, "target_roles": ["VP Product"]}
    )
    async with client_ctx(service) as js:
        assert await sync.push_demand(js) is True
        assert await sync.push_demand(js) is False  # unchanged: not sent again the same day
    areas = {(a["location"], a["role_family"]): a["titles"] for a in service.demand}
    assert areas[("Bengaluru", "technology")] == ["VP Engineering", "Head of Engineering"]
    assert ("Bengaluru", "product") in areas and ("Remote", "technology") in areas
    assert "user_id" not in str(service.demand) and str(account["id"]) not in str(service.demand)


async def test_the_old_company_feeds_are_exported_with_their_ids(client, account, service):
    feed_id = uuid4()
    async with sessionmaker()() as db, db.begin():
        db.add(CompanyFeed(id=feed_id, name="Okta", ats="greenhouse", board="okta"))
    async with (
        sessionmaker()() as db,
        db.begin(),
    ):  # on the shared list (migration 0033 copies the old follows)
        db.add(PlatformCompany(employer_id=feed_id, name="Okta"))
    async with client_ctx(service) as js:
        await sync.pull(js)
        assert await sync.export_legacy(js) == 0  # once only
    assert service.rows[str(feed_id)]["board"] == "okta"
    (company,) = (await page(client, account))["companies"]
    assert company["id"] == str(feed_id) and company["ats"] == "greenhouse"


async def test_the_pull_task_notes_an_unavailable_service(client, service):
    from app.modules.sources import tasks

    service.up = False
    await tasks.pull(timestamp=int(datetime.now(UTC).timestamp()))  # doesn't raise
    async with sessionmaker()() as db:
        row = await db.get(JobSearchSync, 1)
    assert row.last_error == "Job search service unavailable (ConnectError)"
    service.up = True
    await tasks.pull(timestamp=int(datetime.now(UTC).timestamp()))
    async with sessionmaker()() as db:
        row = await db.get(JobSearchSync, 1)
    assert row.last_error is None and row.pulled_at is not None


@pytest.mark.nodb
def test_the_page_says_when_the_service_reads_the_boards_next():
    from app.core.worker import app
    from app.modules.sources.tasks import PULL, check_times, next_check

    assert next_check(datetime(2026, 11, 4, 0, 30, tzinfo=UTC)) == datetime(2026, 11, 4, 3, 0, tzinfo=UTC)
    assert next_check(datetime(2026, 11, 4, 3, 0, tzinfo=UTC)) == datetime(2026, 11, 4, 6, 0, tzinfo=UTC)
    assert next_check(datetime(2026, 11, 4, 22, 5, tzinfo=UTC)) == datetime(2026, 11, 5, 0, 0, tzinfo=UTC)
    now = datetime(2026, 11, 5, 9, 10, tzinfo=UTC)
    assert check_times("Asia/Kolkata", now) == "every 3 hours (next at 17:30 IST)"
    assert check_times("Asia/Dubai", now) == "every 3 hours (next at 16:00 UTC+04)"
    assert check_times("Asia/Kathmandu", now) == "every 3 hours (next at 17:45 UTC+05:45)"
    crons = {t.task.name: t.cron for t in app.periodic_registry.periodic_tasks.values()}
    assert crons[PULL] == "*/5 * * * *"


async def test_the_sources_page_uses_the_users_time_zone(client, account, service):
    await client.patch("/api/v1/me", json={"timezone": "Europe/London"}, headers=account["headers"])
    assert (await page(client, account))["check_times"].endswith(" GMT)")


async def test_closed_flag_lands_on_the_job(client, account, service):
    eid = await follow(client, account)
    service.publish("NEW", eid, "7001", "Director of Engineering", "Bengaluru, India")
    async with client_ctx(service) as js:
        await sync.pull(js)
    service.publish(
        "CLOSED",
        eid,
        "7001",
        "Director of Engineering",
        "Bengaluru, India",
        status="closed",
        closed_at="2026-11-14T03:00:00+00:00",
    )
    async with client_ctx(service) as js:
        await sync.pull(js)
    async with sessionmaker()() as db:
        details = await db.scalar(select(Job.details))
        count = await db.scalar(text("select count(*) from jobs"))
    assert details["closed_on_site"] == "2026-11-14" and count == 1


async def test_a_job_portal_link_is_refused_with_a_clear_reason(client, account, service):
    r = await client.post(
        "/api/v1/sources/companies",
        headers=account["headers"],
        json={"name": "Acme", "url": "https://www.linkedin.com/company/acme/jobs"},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "job_portal"
    assert (await page(client, account))["companies"] == []


def test_every_company_site_source_counts_as_a_company_careers_site():
    from app.modules.catalog.parsers.base import COMPANY_SITES
    from app.modules.jobs.duplicates import FEEDS

    assert {"workday", "oracle", "eightfold", "careers_page"} <= COMPANY_SITES and FEEDS == COMPANY_SITES


async def test_the_last_runs_jobs_include_the_ones_left_out_with_the_reason(client, account, service):
    """User, 2026-11-16: "see last run jobs even if not matching". Left-out jobs are listed with why, and can be
    added to the list anyway."""
    h = account["headers"]
    assert (await client.get("/api/v1/sources/last-run/jobs", headers=h)).status_code == 404  # no run yet
    await client.post("/api/v1/profiles", headers=h, json=VALID_PROFILE)
    eid = await follow(client, account)
    service.publish_acme(eid)
    service.check_result["acmecloud"] = {"found": 4, "new": 4, "error": None}
    async with client_ctx(service) as js:
        await sync.check_user(js, account["id"])

    r = await client.get("/api/v1/sources/last-run/jobs", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["in_list"], body["left_out"]) == (2, 2)
    out = {i["title"]: i["why"] for i in body["items"] if not i["in_list"]}
    assert out["Software Engineer II"].startswith("Below your level")
    assert out["Director, Finance"].startswith("Another field")
    assert all(i["user_job_id"] for i in body["items"] if i["in_list"])

    finance = next(i for i in body["items"] if i["title"] == "Director, Finance")
    r = await client.post(f"/api/v1/sources/last-run/jobs/{finance['job_id']}", headers=h)
    assert r.status_code == 201 and r.json()["in_list"] is True
    assert len(await my_jobs(account["id"])) == 3
    again = await client.post(f"/api/v1/sources/last-run/jobs/{finance['job_id']}", headers=h)
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_in_list"
    unknown = "00000000-0000-0000-0000-000000000000"
    assert (await client.post(f"/api/v1/sources/last-run/jobs/{unknown}", headers=h)).status_code == 404
    assert (await client.get("/api/v1/sources/last-run/jobs")).status_code == 401


async def test_a_checks_board_counts_are_not_the_last_runs_jobs(client, account, service):
    """2026-11-16: a run pulled 2 jobs, but the page said 120 fit: the check that followed it wrote the boards'
    sizes just after the pull, inside the window. Only the pull's own lines count."""
    await client.post("/api/v1/profiles", headers=account["headers"], json=VALID_PROFILE)
    eid = await follow(client, account)
    service.publish_acme(eid)
    service.check_result["acmecloud"] = {"found": 4, "new": 4, "error": None}
    async with client_ctx(service) as js:
        await sync.check_user(js, account["id"])
    async with user_scope(account["id"]) as db:  # a later check line: the board lists 109 jobs
        db.add(SourceRun(user_id=account["id"], source="company_feed", employer_id=UUID(eid), found=109))
    run = (await page(client, account))["last_run"]
    assert run["fit"] == 2


async def test_a_followed_companys_jobs_say_which_the_last_check_found(client, account, service):
    """User, 2026-11-16: "when I click on 22 jobs, it does not say which are those jobs". Every open job at the
    company, in your list or left out and why, and the ones its last check found."""
    h = account["headers"]
    await client.post("/api/v1/profiles", headers=h, json=VALID_PROFILE)
    eid = await follow(client, account)
    service.publish_acme(eid)
    async with client_ctx(service) as js:
        await sync.pull(js)
    service.last_check[eid] = "2026-11-16T09:00:00+00:00"
    service.publish(
        "NEW", eid, "7009", "VP Engineering", "Bengaluru, India", first_seen_at="2026-11-16T09:01:00+00:00"
    )
    async with client_ctx(service) as js:
        await sync.pull(js)

    r = await client.get(f"/api/v1/sources/companies/{eid}/jobs", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["total"], body["new"], body["in_list"], body["left_out"]) == (5, 1, 3, 2)
    assert body["items"][0]["title"] == "VP Engineering" and body["items"][0]["new"] is True
    out = {i["title"]: i["why"] for i in body["items"] if not i["in_list"]}
    assert out["Software Engineer II"].startswith("Below your level")
    assert body["checked_at"].startswith("2026-11-16T09:00")

    junior = next(i for i in body["items"] if i["title"] == "Software Engineer II")
    added = await client.post(f"/api/v1/sources/companies/{eid}/jobs/{junior['job_id']}", headers=h)
    assert added.status_code == 201 and added.json()["in_list"] is True
    assert len(await my_jobs(account["id"])) == 4
    again = await client.post(f"/api/v1/sources/companies/{eid}/jobs/{junior['job_id']}", headers=h)
    assert again.status_code == 409


async def test_only_a_followed_companys_jobs_can_be_listed_or_added(client, account, service):
    h = account["headers"]
    eid = await follow(client, account)
    service.publish_acme(eid)
    async with client_ctx(service) as js:
        await sync.pull(js)
    other = (await service.register(name="Other", system="greenhouse", board="other"))["id"]
    assert (await client.get(f"/api/v1/sources/companies/{other}/jobs", headers=h)).status_code == 404
    unknown = "00000000-0000-0000-0000-000000000000"
    r = await client.post(f"/api/v1/sources/companies/{eid}/jobs/{unknown}", headers=h)
    assert r.status_code == 404
    service.up = False
    r = await client.get(f"/api/v1/sources/companies/{eid}/jobs", headers=h)
    assert r.status_code == 503 and r.json()["error"]["code"] == "jobsearch_unavailable"
    assert (await client.get(f"/api/v1/sources/companies/{eid}/jobs")).status_code == 401


async def test_a_job_seeker_sees_every_job_from_the_shared_sources(client, account, service):
    """2026-11-17: the admins keep one list of companies; a job seeker gets the jobs that fit, and sees all of them
    in Jobs -> From sources, where the ones left out can be added."""
    seeker = await signup(client)
    client.cookies.clear()
    h = auth(seeker["access_token"])
    seeker_id = UUID(seeker["user"]["id"])
    await client.post("/api/v1/profiles", headers=h, json=VALID_PROFILE)
    eid = await follow(client, account)  # an admin adds the company
    service.publish_acme(eid)
    async with client_ctx(service) as js:
        await sync.pull(js)
    assert sorted(await db_titles(seeker_id)) == ["Director of Engineering, Platform", "Principal Engineer"]

    r = await client.get("/api/v1/sources/jobs", headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["total"], out["in_list"], out["left_out"], out["new"]) == (4, 2, 2, 4)
    left = [i for i in out["items"] if not i["in_list"]]
    assert all(i["why"] for i in left)
    r = await client.post(f"/api/v1/sources/jobs/{left[0]['job_id']}", headers=h)
    assert r.status_code == 201 and r.json()["in_list"] is True
    assert (await client.post(f"/api/v1/sources/jobs/{left[0]['job_id']}", headers=h)).status_code == 409
    # Only jobs the sources brought this user can be added this way.
    assert (await client.post(f"/api/v1/sources/jobs/{uuid4()}", headers=h)).status_code == 404
