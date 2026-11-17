"""The internal API: the token, employers, checks, the event feed, demand, health and the job APIs."""

from uuid import uuid4

import httpx
import pytest

from jobsearch import resolver, service
from jobsearch.config import get_settings
from jobsearch.connectors import BoardNotFound, BoardResult, Posting, adzuna, feeds
from tests.conftest import sample


@pytest.fixture
def fake_boards(monkeypatch):
    """Every board serves the Greenhouse sample; 'gone' doesn't exist; 'down' doesn't answer."""
    calls = []

    async def fetch_board(system, board, company, http, known=None, max_details=None, skip=None):
        calls.append(board)
        if board == "gone":
            raise BoardNotFound(board)
        if board == "down":
            raise httpx.ConnectTimeout("slow")
        return feeds.postings_from_greenhouse(sample("greenhouse.json"), company)

    monkeypatch.setattr(service, "fetch_board", fetch_board)
    return calls


async def add(api, board="acmecloud", name="Acme Cloud", **kw) -> dict:
    r = await api.post("/v1/employers", json={"system": "greenhouse", "board": board, "name": name, **kw})
    assert r.status_code in (200, 201), r.text
    return r.json()


async def test_every_call_needs_the_service_token(api):
    r = await api.get("/v1/events", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized" and r.json()["error"]["request_id"]
    r = await api.get("/v1/sources", headers={"Authorization": ""})
    assert r.status_code == 401
    assert (await api.get("/healthz", headers={"Authorization": ""})).status_code == 200


async def test_registering_a_board_is_idempotent_and_can_keep_an_id(api):
    r = await api.post("/v1/employers", json={"url": "https://boards.greenhouse.io/okta", "name": "Okta"})
    assert r.status_code == 201
    okta = r.json()
    assert (okta["system"], okta["board"], okta["board_url"]) == (
        "greenhouse",
        "okta",
        "https://boards.greenhouse.io/okta",
    )
    again = await api.post("/v1/employers", json={"system": "greenhouse", "board": "OKTA"})
    assert again.status_code == 200 and again.json()["id"] == okta["id"]
    kept = uuid4()
    imported = await add(api, board="stripe", name="Stripe", id=str(kept))
    assert imported["id"] == str(kept)


async def test_a_workday_link_registers_a_workday_board(api):
    r = await api.post(
        "/v1/employers", json={"url": "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite"}
    )
    assert r.status_code == 201
    assert r.json()["board"] == "nvidia.wd5.myworkdayjobs.com/nvidia/NVIDIAExternalCareerSite"
    assert r.json()["board_url"] == "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"


async def test_bad_registrations_are_refused(api):
    r = await api.post(
        "/v1/employers", json={"url": "https://jobs.lever.co/"}
    )  # a hiring system, but no board
    assert r.status_code == 400 and r.json()["error"]["code"] == "unknown_board"
    r = await api.post("/v1/employers", json={"name": "Nobody"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    r = await api.post("/v1/employers", json={"system": "workday", "board": "nvidia"})
    assert r.status_code == 400


async def test_a_check_stores_the_jobs_and_the_feed_announces_them(api, fake_boards):
    acme = await add(api)
    r = await api.post(f"/v1/employers/{acme['id']}/check")
    assert r.status_code == 200
    run = r.json()
    assert (run["found"], run["new"], run["error"]) == (4, 4, None)

    feed = (await api.get("/v1/events", params={"after": 0, "limit": 3})).json()
    assert [e["type"] for e in feed["events"]] == ["NEW", "NEW", "NEW"]
    first = feed["events"][0]["listing"]
    assert first["employer_id"] == acme["id"] and first["company"] == "Acme Cloud"
    assert first["sources"][0]["source"] == "greenhouse" and first["status"] == "active"
    rest = (await api.get("/v1/events", params={"after": feed["next_cursor"]})).json()
    assert len(rest["events"]) == 1
    empty = (await api.get("/v1/events", params={"after": rest["next_cursor"]})).json()
    assert empty == {"events": [], "next_cursor": rest["next_cursor"]}

    detail = await api.get(f"/v1/employers/{acme['id']}")
    assert detail.json()["jobs_in_scope"] == 4 and detail.json()["last_run"]["new"] == 4
    listing = (await api.get(f"/v1/listings/{first['listing_id']}")).json()
    assert listing["versions"] == [] and listing["title"] == first["title"]


async def test_an_employers_listings_say_which_the_last_check_found(api, fake_boards):
    acme = await add(api)
    await api.post(f"/v1/employers/{acme['id']}/check")
    r = await api.get(f"/v1/employers/{acme['id']}/listings")
    assert r.status_code == 200
    body = r.json()
    assert len(body["listings"]) == 4 and body["last_run"]["found"] == 4
    assert all(item["description"] is None and item["sources"] for item in body["listings"])
    started = body["last_run"]["started_at"]
    assert all(item["first_seen_at"] >= started for item in body["listings"])
    assert (await api.get(f"/v1/employers/{uuid4()}/listings")).status_code == 404


async def test_a_second_check_within_minutes_is_refused(api, fake_boards):
    acme = await add(api)
    await api.post(f"/v1/employers/{acme['id']}/check")
    r = await api.post(f"/v1/employers/{acme['id']}/check")
    assert r.status_code == 409 and r.json()["error"]["code"] == "checked_recently"


async def test_a_board_that_is_gone_or_down_is_reported_not_raised(api, fake_boards):
    gone = await add(api, board="gone", name="Gone")
    run = (await api.post(f"/v1/employers/{gone['id']}/check")).json()
    assert run["error"] == "No job board 'gone' on Greenhouse any more"
    down = await add(api, board="down", name="Down")
    run = (await api.post(f"/v1/employers/{down['id']}/check")).json()
    assert run["error"] == "Greenhouse didn't answer (ConnectTimeout)"
    health = {s["connector"]: s for s in (await api.get("/v1/sources")).json()}
    assert health["greenhouse"]["failures_24h"] == 2 and health["greenhouse"]["boards"] == 2
    assert health["workday"]["boards"] == 0 and health["adzuna"]["configured"] is False


async def test_unknown_ids_are_not_found(api):
    for path in (f"/v1/employers/{uuid4()}", f"/v1/listings/{uuid4()}"):
        r = await api.get(path)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert (await api.post(f"/v1/employers/{uuid4()}/check")).status_code == 404


async def test_employers_by_id(api):
    a, b = await add(api, board="a1", name="Alpha"), await add(api, board="b1", name="Beta")
    await add(api, board="c1", name="Gamma")
    got = (await api.get("/v1/employers", params=[("ids", a["id"]), ("ids", b["id"])])).json()
    assert [e["name"] for e in got] == ["Alpha", "Beta"]


async def test_demand_replaces_the_search_areas(api):
    r = await api.put(
        "/v1/demand/search-areas",
        json={
            "areas": [
                {"location": "Bengaluru", "role_family": "technology", "titles": ["VP Engineering"]},
                {"location": "bengaluru", "role_family": "Technology", "titles": ["Head of Engineering"]},
                {"location": "Pune", "role_family": "product", "titles": []},
            ]
        },
    )
    assert r.json() == {"active": 2}
    r = await api.put(
        "/v1/demand/search-areas", json={"areas": [{"location": "Pune", "role_family": "product"}]}
    )
    assert r.json() == {"active": 1}
    bad = await api.put("/v1/demand/search-areas", json={"areas": [{"location": "", "role_family": "x"}]})
    assert bad.status_code == 422


async def test_lookup_and_suggestions(api, monkeypatch):
    async def lookup(query):
        return [resolver.Found("greenhouse", "okta", 12, 300, ["VP Engineering"])]

    monkeypatch.setattr(resolver, "lookup", lookup)
    found = (await api.post("/v1/employers/lookup", json={"query": "Okta"})).json()
    assert found[0]["board_url"] == "https://boards.greenhouse.io/okta" and found[0]["in_scope"] == 12
    assert (await api.post("/v1/employers/lookup", json={"query": "x"})).status_code == 422
    suggested = (await api.get("/v1/employers/suggested")).json()
    assert {"name": "NVIDIA", "system": "workday"}.items() <= next(
        s for s in suggested if s["name"] == "NVIDIA"
    ).items()


async def test_job_apis_search_each_area_within_the_daily_quota(api, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "adzuna_app_id", "id")
    monkeypatch.setattr(s, "adzuna_app_key", "key")
    monkeypatch.setattr(s, "adzuna_daily_calls", 2)
    asked = []

    async def search(role, location, http):
        asked.append((role, location))
        return adzuna.postings_from_adzuna(sample("adzuna.json"))

    monkeypatch.setattr(adzuna, "search", search)
    await api.put(
        "/v1/demand/search-areas",
        json={
            "areas": [
                {"location": "Bengaluru", "role_family": "technology", "titles": ["VP Engineering", "CTO"]},
                {"location": "Pune", "role_family": "product", "titles": ["VP Product"]},
            ]
        },
    )
    runs = await service.run_apis(http=httpx.AsyncClient())
    assert asked == [("VP Engineering", "Bengaluru"), ("CTO", "Bengaluru")]  # the quota (2) stops Pune
    assert runs[0].new == 2 and runs[0].error is None
    assert runs[1].error == "Daily Adzuna quota used up"
    feed = (await api.get("/v1/events")).json()
    assert {e["listing"]["employer_id"] for e in feed["events"]} == {None}


async def test_a_company_careers_site_registers_and_a_job_portal_is_refused(api):
    r = await api.post(
        "/v1/employers", json={"url": "https://careers.arm.com/job/bengaluru/x/33099/1", "name": "Arm"}
    )
    assert r.status_code == 201
    assert (r.json()["system"], r.json()["board"], r.json()["board_url"]) == (
        "careers_page",
        "careers.arm.com",
        "https://careers.arm.com/",
    )
    for link in ("https://www.linkedin.com/company/arm/jobs", "https://www.naukri.com/arm-jobs"):
        r = await api.post("/v1/employers", json={"url": link})
        assert r.status_code == 400 and r.json()["error"]["code"] == "job_portal", link
        r = await api.post("/v1/employers/lookup", json={"query": link})
        assert r.status_code == 400 and r.json()["error"]["code"] == "job_portal", link


async def test_careers_pages_found_abroad_are_not_read_again(api, monkeypatch):
    seen_skip = []

    async def fetch_board(system, board, company, http, known=None, max_details=None, skip=None):
        seen_skip.append(set(skip or ()))
        return BoardResult(
            [
                Posting(
                    source="careers_page",
                    source_job_id="1001",
                    title="Director",
                    company=company,
                    location="Pune, India",
                    description="Lead.",
                )
            ],
            total=2,
            out_of_scope=("1002",),
        )

    monkeypatch.setattr(service, "fetch_board", fetch_board)
    acme = (await api.post("/v1/employers", json={"url": "https://careers.acme.com", "name": "Acme"})).json()
    first = (await api.post(f"/v1/employers/{acme['id']}/check")).json()
    assert first["new"] == 1
    # The scheduled read (no 10-minute limit there): the page found abroad is passed back as one to skip.
    await service.check_board(await _board_id(acme["id"]))
    assert seen_skip == [set(), {"1002"}]


async def _board_id(employer_id: str):
    from sqlalchemy import select

    from jobsearch.db import sessionmaker
    from jobsearch.models import EmployerBoard

    async with sessionmaker()() as db:
        return await db.scalar(select(EmployerBoard.id).where(EmployerBoard.employer_id == employer_id))
