"""Milestone 13 A: "Not for me" with a reason, what BrewMyJob learns from it, and forgetting it."""

import pytest

from app.modules.feedback.learning import SENIOR_YEARS, Pref, learn, matching, years_asked, years_cut
from tests.test_jobs import find
from tests.test_matching import run_scoring, setup_user

TECH = {"technology"}


@pytest.mark.nodb
def test_what_a_reason_teaches():
    assert learn("company", "VP Engineering", "Okta", "Bengaluru", TECH) == [
        Pref("company", "Okta", "Jobs at Okta")
    ]
    assert learn("company", "VP Engineering", "Leading MNC", "Bengaluru", TECH) == []  # nobody to name
    assert learn("location", "VP Engineering", "Okta", "Pune, Maharashtra", TECH) == [
        Pref("location", "pune", "Jobs in Pune")
    ]
    assert learn("field", "Head of Marketing", "Okta", None, TECH) == [
        Pref("field", "marketing", "Marketing roles")
    ]
    assert learn("field", "Director of Engineering", "Okta", None, TECH) == []  # the user's own field: no
    assert learn("too_junior", "Engineering Manager", "Okta", None, TECH) == [
        Pref(
            "level_min",
            "4",
            "Roles below manager level (manager roles asking for under 12 years score 10-20% lower)",
        )
    ]
    assert learn("too_senior", "Chief Technology Officer", "Okta", None, TECH) == [
        Pref("level_max", "8", "Roles above SVP level")
    ]
    assert learn("salary", "VP Engineering", "Okta", None, TECH) == []  # recorded only


@pytest.mark.nodb
def test_which_jobs_a_preference_covers():
    prefs = [
        Pref("company", "Okta Inc.", "Jobs at Okta"),
        Pref("location", "pune", "Jobs in Pune"),
        Pref("level_min", "5", "Roles below director level"),
    ]
    assert matching(prefs, "VP Engineering", "Okta", "Bengaluru").label == "Jobs at Okta"
    assert matching(prefs, "VP Engineering", "Zscaler", "Pune").label == "Jobs in Pune"
    assert matching(prefs, "VP Engineering", "Zscaler", "Pune, Bengaluru") is None  # Bengaluru is still fine
    assert matching(prefs, "VP Engineering", "Zscaler", "Remote, Pune") is None
    assert (
        matching(prefs, "Engineering Manager", "Zscaler", "Bengaluru").label == "Roles below director level"
    )
    assert matching(prefs, "Director of Engineering", "Zscaler", "Bengaluru") is None


async def not_for_me(client, account, job: dict, reason: str, **kw):
    return await client.post(
        f"/api/v1/jobs/{job['id']}/not-for-me",
        json={"reason": reason, "version": job["version"], **kw},
        headers=account["headers"],
    )


async def test_not_for_me_ignores_the_job_and_learns_its_city_until_forgotten(client, account):
    await setup_user(client, account)
    await run_scoring(account)
    chief = await find(client, account, "Chief Engineer")  # Bengaluru East
    cfo_before = (await find(client, account, "SEG & India CFO"))["match"]["score"]  # Bangalore Urban

    r = await not_for_me(client, account, chief, "location", note="Too far from home")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "ignored" and d["not_for_me"] == "location"
    assert d["learned"] == "Jobs in Bengaluru" and d["match"]["score"] <= 40
    h = account["headers"]
    (pref,) = (await client.get("/api/v1/preferences/learned", headers=h)).json()
    assert pref["label"] == "Jobs in Bengaluru" and pref["kind"] == "location"

    await run_scoring(account)  # the queued re-score of every job
    cfo = await find(client, account, "SEG & India CFO")
    assert cfo["match"]["score"] <= 40
    detail = (await client.get(f"/api/v1/jobs/{cfo['id']}", headers=h)).json()
    assert "learned" in [p["key"] for p in detail["match"]["points_lost"]]

    r = await client.delete(f"/api/v1/preferences/learned/{pref['id']}", headers=h)
    assert r.status_code == 204
    await run_scoring(account)
    assert (await find(client, account, "SEG & India CFO"))["match"]["score"] == cfo_before
    assert (await client.get("/api/v1/preferences/learned", headers=h)).json() == []


async def test_not_for_me_errors(client, account):
    await setup_user(client, account)
    await run_scoring(account)
    chief = await find(client, account, "Chief Engineer")
    h = account["headers"]
    r = await not_for_me(client, account, chief, "vibes")
    assert (r.status_code, r.json()["error"]["details"][0]["field"]) == (422, "reason")
    r = await not_for_me(client, account, {**chief, "version": chief["version"] + 5}, "company")
    assert r.status_code == 409
    r = await client.patch(
        f"/api/v1/jobs/{chief['id']}", json={"status": "applied", "version": chief["version"]}, headers=h
    )
    assert r.status_code == 200, r.text
    r = await not_for_me(client, account, r.json(), "company")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "not_active")
    missing = {"id": "00000000-0000-0000-0000-000000000000", "version": 1}
    assert (await not_for_me(client, account, missing, "company")).status_code == 404
    r = await client.delete("/api/v1/preferences/learned/00000000-0000-0000-0000-000000000000", headers=h)
    assert r.status_code == 404


async def test_the_feedback_review_lists_new_answers_until_marked_reviewed(client, account):
    from app.feedback_review import mark_done, review

    await setup_user(client, account)
    await run_scoring(account)
    chief = await find(client, account, "Chief Engineer")
    r = await not_for_me(client, account, chief, "other", note="Automotive telematics, not software products")
    assert r.status_code == 200, r.text

    lines = await review(show_all=False)
    text = "\n".join(lines)
    assert "Something else — Automotive telematics" in text and "Learned: nothing (recorded only)" in text
    at = next(i for i, ln in enumerate(lines) if ln.startswith("  Job:     Chief Engineer"))
    short = lines[at - 1].split()[0]

    assert await mark_done([short], "added an automotive specialism") == [f"{short} reviewed"]
    assert "Chief Engineer" not in "\n".join(await review(show_all=False))
    assert "added an automotive specialism" in "\n".join(await review(show_all=True))
    assert await mark_done(["zzzzzzzz"], None) == ["No feedback with those ids."]


@pytest.mark.nodb
def test_too_junior_on_a_director_caps_lower_levels_and_takes_a_share_off_directors_with_fewer_years():
    # User, 2026-11-11: "Any Director roles with 10+ years you can cap; they will have less salary as well."
    (pref,) = learn("too_junior", "Program Director", "Acme", None, {"technology"})
    assert pref == Pref(
        "level_min",
        "6",
        "Roles below director level (director roles asking for under 12 years score 10-20% lower)",
    )
    # A Director asking for fewer years is not capped but loses 10% (9-11 years) or 20% (under 9) of its score.
    assert matching([pref], "Director - Software Engineering", "Capital One", "Bengaluru", 10) is None
    assert years_cut([pref], "Director - Software Engineering", 10) == 0.10
    assert years_cut([pref], "Director of Engineering", 8) == 0.20
    assert (
        years_cut([pref], "Director of Engineering", SENIOR_YEARS) == 0 == years_cut([pref], "Director", None)
    )
    assert years_cut([pref], "VP Engineering", 8) == 0
    assert matching([pref], "Director of Engineering", "Acme", "Bengaluru", SENIOR_YEARS) is None  # 12: kept
    assert matching([pref], "Director of Engineering", "Acme", "Bengaluru", None) is None  # unstated: kept
    assert matching([pref], "Senior Engineering Manager", "Acme", "Bengaluru", 20) == pref  # below director
    assert matching([pref], "VP Engineering", "Acme", "Bengaluru", 8) is None

    assert years_asked("15-20 Yrs") == 15 and years_asked("20+ years") == 20 and years_asked("12") == 12
    capital_one = "At least 5 years of people management. At least 7 years of… 10+ years of experience coding"
    assert years_asked(None, capital_one) == 10
    assert years_asked(None, "Lead a team of 12 engineers.") is None
