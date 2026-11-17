"""Jobs the user finds on Google and adds by hand (user, 2026-11-14: "route 1"; jobs/found.py).

BrewMyJob gives the searches and takes the link and the facts the user typed; it never opens the portal page.
"""

import pytest

from app.modules.jobs import found
from tests.conftest import VALID_PROFILE

WOOLWORTHS = (
    "https://in.linkedin.com/jobs/view/head-of-engineering-service-enablement-platforms-at-woolworths-group-4490581539"
    "?trk=public_jobs_topcard-title"
)


# --- The searches (no database) -------------------------------------------------------------------------


@pytest.mark.nodb
def test_each_role_and_place_gets_a_search_per_portal():
    (s, remote) = found.searches(["Head of Engineering"], ["Bengaluru", "Remote"])
    assert s.queries == {
        "linkedin": 'site:linkedin.com/jobs/view "Head of Engineering" ("Bengaluru" OR "Bangalore")',
        "naukri": 'site:naukri.com/job-listings "Head of Engineering" ("Bengaluru" OR "Bangalore")',
        "foundit": 'site:foundit.in/job "Head of Engineering" ("Bengaluru" OR "Bangalore")',
    }
    assert remote.queries["linkedin"].endswith('"Head of Engineering" remote')


@pytest.mark.nodb
def test_searches_drop_repeats_and_stay_few():
    roles = ["VP Engineering", "vp engineering ", *(f"Role {i}" for i in range(20))]
    out = found.searches(roles, ["New Delhi", "Pune", "pune"])
    assert out[0].queries["naukri"] == 'site:naukri.com/job-listings "VP Engineering" "New Delhi"'
    assert len({s.role for s in out}) == found.MAX_ROLES
    assert {s.place for s in out} == {"New Delhi", "Pune"}
    assert found.searches(["CTO"], [])[0].queries["foundit"] == 'site:foundit.in/job "CTO"'
    # One place spelt two ways (sign-up said Bengaluru, the profile Bangalore) is one search.
    (one,) = found.searches(["CTO"], ["Bengaluru", "Bangalore", "bengaluru"])
    assert one.place == "Bengaluru"


@pytest.mark.nodb
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (WOOLWORTHS, ("linkedin", "4490581539", "https://www.linkedin.com/jobs/view/4490581539/")),
        ("https://www.linkedin.com/jobs/view/4490581539/", ("linkedin", "4490581539", None)),
        (
            "https://www.linkedin.com/jobs/search/?currentJobId=4490581539&keywords=x",
            ("linkedin", "4490581539", None),
        ),
        (
            "https://www.naukri.com/job-listings-head-engineering-acme-bengaluru-15-to-20-years-140525901234?src=x",
            (
                "naukri",
                "140525901234",
                "https://www.naukri.com/job-listings-head-engineering-acme-bengaluru-15-to-20-years-140525901234",
            ),
        ),
        (
            "https://www.foundit.in/job/head-of-engineering-platforms-hcl-techbee-bengaluru-bangalore-58167202",
            ("foundit", "58167202", None),
        ),
    ],
)
def test_the_link_gives_the_portal_and_its_job_id(url, expected):
    source, job_id, canonical = found.portal_job(url)
    assert (source, job_id) == expected[:2]
    if expected[2]:
        assert canonical == expected[2]


@pytest.mark.nodb
@pytest.mark.parametrize(
    "url",
    [
        "linkedin.com/jobs/view/4490581539",  # no scheme
        "https://www.linkedin.com/company/woolworths",  # not a job
        "https://www.naukri.com/head-of-engineering-jobs-in-bangalore",  # a search page
        "https://careers.woolworthsgroup.com.au/en_GB/apply/JobDetail/x/120428",  # a company site
        "https://evil-linkedin.com/jobs/view/4490581539",
    ],
)
def test_other_links_are_refused(url):
    with pytest.raises(found.NotAJobLink):
        found.portal_job(url)


# --- The endpoints ---------------------------------------------------------------------------------------


async def test_the_searches_come_from_the_users_roles_and_places(client, account):
    await client.post("/api/v1/profiles", headers=account["headers"], json=VALID_PROFILE)
    r = await client.get("/api/v1/jobs/google-searches", headers=account["headers"])
    assert r.status_code == 200
    body = r.json()
    assert [p["id"] for p in body["portals"]] == ["linkedin", "naukri", "foundit"]
    pairs = {(s["role"], s["place"]) for s in body["searches"]}
    # Sign-up places (Bengaluru) and the profile's (Bengaluru, Remote), once each.
    assert pairs == {
        (role, place) for role in VALID_PROFILE["target_roles"] for place in ("Bengaluru", "Remote")
    }


async def test_the_searches_need_sign_in(client):
    assert (await client.get("/api/v1/jobs/google-searches")).status_code == 401


async def test_a_found_job_is_added_scored_and_not_added_twice(client, account):
    body = {
        "url": WOOLWORTHS,
        "title": "Head of Engineering (Service Enablement Platforms)",
        "company": "Woolworths Group",
        "location": "Bengaluru (Hybrid)",
        "description": "Lead the engineering teams that build Woolworths' service enablement platforms. " * 3,
    }
    r = await client.post("/api/v1/jobs/found", headers=account["headers"], json=body)
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["job"]["title"] == body["title"]
    assert job["job"]["location"] == "Bengaluru" and job["job"]["work_model"] == "Hybrid"
    assert job["job"]["verified"] is False
    assert job["job"]["description_source"] == "you"
    assert [s["source"] for s in job["job"]["sources"]] == ["linkedin"]
    assert job["job"]["sources"][0]["url"] == "https://www.linkedin.com/jobs/view/4490581539/"

    again = await client.post(
        "/api/v1/jobs/found",
        headers=account["headers"],
        json={**body, "url": "https://www.linkedin.com/jobs/view/4490581539/", "description": None},
    )
    assert again.status_code == 201 and again.json()["id"] == job["id"]
    listed = (await client.get("/api/v1/jobs?status=all", headers=account["headers"])).json()
    assert listed["total"] == 1


async def test_a_found_job_needs_a_portal_job_link_and_a_whole_description(client, account):
    base = {"url": WOOLWORTHS, "title": "Head of Engineering", "company": "Woolworths Group"}
    r = await client.post(
        "/api/v1/jobs/found",
        headers=account["headers"],
        json={**base, "url": "https://careers.woolworthsgroup.com.au/en_GB/apply/JobDetail/x/120428"},
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "not_a_job_link"
    assert r.json()["error"]["details"][0]["field"] == "url"
    short = await client.post(
        "/api/v1/jobs/found", headers=account["headers"], json={**base, "description": "Too short"}
    )
    assert short.status_code == 422
    assert [d["field"] for d in short.json()["error"]["details"]] == ["description"]
    assert (await client.post("/api/v1/jobs/found", json=base)).status_code == 401


def test_roles_written_with_or_and_a_city_are_searched_as_written():
    """The roles on Find on Google are shared with Google Alerts (2026-11-17): alternatives with OR, and a role
    that names its city gets one search."""
    role = '("Technology Director" OR "Engineering Director") ("Bengaluru" OR "Bangalore")'
    (s,) = found.searches([role], ["Bengaluru", "Pune"])
    assert s.place is None
    assert s.queries["linkedin"] == f"site:linkedin.com/jobs/view {role}"


async def test_the_searches_use_the_roles_set_for_google(client, account):
    await client.post("/api/v1/profiles", headers=account["headers"], json=VALID_PROFILE)
    r = await client.put(
        "/api/v1/alerts/roles", headers=account["headers"], json={"roles": ["Engineering Director"]}
    )
    assert r.status_code == 200
    out = (await client.get("/api/v1/jobs/google-searches", headers=account["headers"])).json()
    assert out["roles_custom"] is True and {s["role"] for s in out["searches"]} == {'"Engineering Director"'}
