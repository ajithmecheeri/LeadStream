"""Skill Match profiles (user feedback 2026-11-13): one per resume, made from it; skills from the resume refresh
with it, skills the user added stay; deleting the resume deletes its profile."""

import pytest

from app.modules.matching.scoring import JobInput, ProfileInput, ResumeInput, score_job
from app.modules.profiles.service import target_roles
from tests import samples
from tests.test_matching import match_profiles


async def add_resume(client, h, text: str, label: str) -> dict:
    r = await client.post("/api/v1/resumes", json={"text": text, "label": label}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


async def test_a_new_resume_brings_its_match_profile(client, account):
    h = account["headers"]
    resume = await add_resume(client, h, samples.RESUME, "Cloud and AI")
    (p,) = await match_profiles(client, account)
    assert (p["resume_id"], p["resume_label"], p["name"]) == (resume["id"], "Cloud and AI", "Cloud and AI")
    assert {"Kubernetes", "Terraform", "Python"} <= set(p["resume_skills"])
    assert "VP Engineering" in p["target_roles"]  # from the headline "VP, Engineering | …"
    assert p["skills"] == [] and p["not_in_resume"] == [] and p["active"] is True


async def test_skills_i_add_stay_and_the_ones_the_resume_lacks_are_flagged(client, account):
    h = account["headers"]
    await add_resume(client, h, samples.RESUME, "Cloud and AI")
    (p,) = await match_profiles(client, account)

    r = await client.post(f"/api/v1/profiles/{p['id']}/skills", headers=h, json={"skill": "FinOps"})
    assert r.status_code == 200, r.text
    assert r.json()["skills"] == ["FinOps"] and r.json()["not_in_resume"] == ["FinOps"]
    # Already there (from the resume, any case): nothing changes.
    r = await client.post(f"/api/v1/profiles/{p['id']}/skills", headers=h, json={"skill": "kubernetes"})
    assert r.json()["skills"] == ["FinOps"]

    r = await client.post(f"/api/v1/profiles/{p['id']}/refresh", headers=h)
    assert r.status_code == 200 and r.json()["skills"] == ["FinOps"]


async def test_a_new_version_of_the_resume_refreshes_its_skills_and_keeps_mine(client, account):
    h = account["headers"]
    resume = await add_resume(client, h, samples.RESUME, "Cloud and AI")
    (p,) = await match_profiles(client, account)
    await client.post(f"/api/v1/profiles/{p['id']}/skills", headers=h, json={"skill": "FinOps"})

    better = samples.RESUME.replace("Terraform", "Terraform, FinOps")
    r = await client.post(f"/api/v1/resumes/{resume['id']}/replace", headers=h, json={"text": better})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Cloud and AI" and r.json()["is_primary"] is True

    (after,) = await match_profiles(client, account)
    assert after["id"] == p["id"]  # the same profile, with its settings
    assert "FinOps" in after["resume_skills"] and after["skills"] == ["FinOps"]
    assert after["not_in_resume"] == []  # now in the resume: no warning


async def test_replacing_a_resume_with_another_one_already_kept_is_refused(client, account):
    h = account["headers"]
    first = await add_resume(client, h, samples.RESUME, "Cloud and AI")
    await add_resume(client, h, samples.RESUME_DELIVERY, "Delivery")
    r = await client.post(
        f"/api/v1/resumes/{first['id']}/replace", headers=h, json={"text": samples.RESUME_DELIVERY}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate"


async def test_deleting_a_resume_deletes_its_match_profile(client, account):
    h = account["headers"]
    await add_resume(client, h, samples.RESUME, "Cloud and AI")
    delivery = await add_resume(client, h, samples.RESUME_DELIVERY, "Delivery")
    assert [p["resume_label"] for p in await match_profiles(client, account)] == ["Cloud and AI", "Delivery"]

    assert (await client.delete(f"/api/v1/resumes/{delivery['id']}", headers=h)).status_code == 204
    assert [p["resume_label"] for p in await match_profiles(client, account)] == ["Cloud and AI"]


async def test_a_resumes_profile_is_deleted_with_the_resume_only(client, account):
    h = account["headers"]
    await add_resume(client, h, samples.RESUME, "Cloud and AI")
    (p,) = await match_profiles(client, account)
    r = await client.delete(f"/api/v1/profiles/{p['id']}", headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "made_from_resume"


async def test_refresh_and_add_skill_errors(client, account):
    h = account["headers"]
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.post(f"/api/v1/profiles/{missing}/refresh", headers=h)).status_code == 404
    r = await client.post(f"/api/v1/profiles/{missing}/skills", headers=h, json={"skill": "Go"})
    assert r.status_code == 404
    # A profile made through the API (no resume) has nothing to refresh from.
    from tests.conftest import VALID_PROFILE

    p = (await client.post("/api/v1/profiles", headers=h, json=VALID_PROFILE)).json()
    r = await client.post(f"/api/v1/profiles/{p['id']}/refresh", headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_resume"
    r = await client.post(f"/api/v1/profiles/{p['id']}/skills", headers=h, json={"skill": "x" * 41})
    assert r.status_code == 422


@pytest.mark.nodb
def test_target_roles_come_from_the_headline():
    assert target_roles(
        "VP, Product Development | Enterprise Technology Leader", "VP, Product Development"
    ) == [
        "VP Product Development",
        "Enterprise Technology Leader",
    ]
    assert target_roles(None, None) == []


@pytest.mark.nodb
def test_a_resume_is_judged_with_its_own_profile():
    job = JobInput("VP Engineering", "Acme", "Pune", None, None, None, [], "vp engineering", True)
    bengaluru = ProfileInput(
        "p1", "Cloud", ["VP Engineering"], ["Bengaluru"], [], 1, [], _w(), 85, resume_id="r1"
    )
    pune = ProfileInput("p2", "Delivery", ["VP Engineering"], ["Pune"], [], 1, [], _w(), 85, resume_id="r2")
    resumes = [
        ResumeInput("r1", "Cloud", "vp engineering", set(), None),
        ResumeInput("r2", "Delivery", "", set(), None),
    ]
    from app.modules.matching.scoring import Candidate

    v = score_job(job, Candidate(None, None, set(), [], None, []), [bengaluru, pune], resumes)
    # Pune is ruled out for the Cloud resume's profile, so only the Delivery resume is ranked, by its own profile.
    assert [(s.resume_id, s.profile_id) for s in v.ranking] == [("r2", "p2")] and v.profile_id == "p2"


def _w() -> dict[str, int]:
    from app.modules.profiles.schemas import DEFAULT_WEIGHTS

    return dict(DEFAULT_WEIGHTS)
