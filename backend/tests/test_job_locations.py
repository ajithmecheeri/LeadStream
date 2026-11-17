"""Where the user wants to work: asked at sign-up, asked once of older accounts, used by new match profiles
(Job Search Service step 1, docs/plan-jobsearch-build.md)."""

from sqlalchemy import update

from app.core.db import user_scope
from app.modules.candidate.models import CandidateProfile
from app.modules.profiles.models import SearchProfile
from tests.conftest import PASSWORD, VALID_PROFILE, auth, unique_email


def _signup_body(**kw) -> dict:
    return {
        "email": unique_email(),
        "first_name": "Asha",
        "last_name": "Rao",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
        "accept_terms": True,
        **kw,
    }


async def test_sign_up_keeps_the_places_tidied(client):
    r = await client.post(
        "/api/v1/auth/signup", json=_signup_body(job_locations=[" Bengaluru ", "bengaluru", "Remote", ""])
    )
    assert r.status_code == 201
    cand = (await client.get("/api/v1/candidate", headers=auth(r.json()["access_token"]))).json()
    assert cand["job_locations"] == ["Bengaluru", "Remote"]


async def test_sign_up_needs_at_least_one_place(client):
    for places in (None, [], ["  "], ["x" * 61]):
        body = _signup_body() if places is None else _signup_body(job_locations=places)
        r = await client.post("/api/v1/auth/signup", json=body)
        assert r.status_code == 422, places
        fields = [d["field"] for d in r.json()["error"]["details"]]
        assert any(f.startswith("job_locations") for f in fields), (places, fields)


async def test_an_older_account_answers_once_and_empty_profiles_take_the_places(client, account):
    await client.post("/api/v1/profiles", headers=account["headers"], json=VALID_PROFILE)
    # An account from before sign-up asked, with a profile left empty.
    async with user_scope(account["id"]) as db:
        await db.execute(update(CandidateProfile).values(job_locations=[]))
        await db.execute(update(SearchProfile).values(locations=[]))
    r = await client.put(
        "/api/v1/candidate/job-locations",
        headers=account["headers"],
        json={"job_locations": ["Pune", "Remote"]},
    )
    assert r.status_code == 200 and r.json()["job_locations"] == ["Pune", "Remote"]
    (profile,) = (await client.get("/api/v1/profiles", headers=account["headers"])).json()
    assert profile["locations"] == ["Pune", "Remote"]
    bad = await client.put(
        "/api/v1/candidate/job-locations", headers=account["headers"], json={"job_locations": []}
    )
    assert bad.status_code == 422


async def test_editing_the_profile_without_places_keeps_them(client, account):
    cand = (await client.get("/api/v1/candidate", headers=account["headers"])).json()
    r = await client.put(
        "/api/v1/candidate",
        headers=account["headers"],
        json={"headline": "VP Engineering", "skills": [], "domains": [], "version": cand["version"]},
    )
    assert r.status_code == 200 and r.json()["job_locations"] == ["Bengaluru"]
    r = await client.put(
        "/api/v1/candidate",
        headers=account["headers"],
        json={"skills": [], "domains": [], "job_locations": ["Hyderabad"], "version": r.json()["version"]},
    )
    assert r.json()["job_locations"] == ["Hyderabad"]
