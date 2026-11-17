"""Readiness of Top matches, the blockers on a job, and the answer bank."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.core.db import user_scope
from app.modules.readiness.models import Answer
from tests.test_jobs import find, jobs
from tests.test_matching import run_scoring, set_match_profiles, setup_user


async def top_job(client, account, title: str = "Chief Engineer") -> dict:
    await setup_user(client, account)
    await run_scoring(account)
    job = await find(client, account, title)
    assert job["match"]["band"] in ("strong", "good"), job["match"]
    return job


async def readiness(client, account, job_id: str) -> dict:
    r = await client.get(f"/api/v1/jobs/{job_id}/readiness", headers=account["headers"])
    assert r.status_code == 200, r.text
    return r.json()


async def resolve(client, account, job_id: str, key: str, answer: str | None = None):
    return await client.post(
        f"/api/v1/jobs/{job_id}/blockers/{key}/resolve", json={"answer": answer}, headers=account["headers"]
    )


async def test_a_new_users_top_match_needs_input(client, account):
    job = await top_job(client, account)
    r = await readiness(client, account, job["id"])
    assert r["status"] == "needs_input"
    keys = [b["key"] for b in r["blockers"]]
    # Four common questions nobody has answered yet, and the description the alert didn't carry.
    assert keys[:4] == [
        "question:notice_period",
        "question:current_ctc",
        "question:expected_ctc",
        "question:total_experience",
    ]
    assert "description" in keys
    assert "cover_letter" not in keys  # setup_user added one

    listed = await find(client, account, "Chief Engineer")
    assert listed["readiness"] == {"status": "needs_input", "blockers": len(keys)}
    detail = (await client.get(f"/api/v1/jobs/{job['id']}", headers=account["headers"])).json()
    assert detail["readiness"]["blockers"] == r["blockers"]


async def test_answering_once_clears_the_question_on_every_job(client, account):
    job = await top_job(client, account)
    other = await find(client, account, "Principal AI Architect")
    r = await resolve(client, account, job["id"], "question:notice_period", "  90 days  ")
    assert r.status_code == 200, r.text
    assert "question:notice_period" not in [b["key"] for b in r.json()["blockers"]]
    assert "question:notice_period" not in [
        b["key"] for b in (await readiness(client, account, other["id"]))["blockers"]
    ]

    bank = {
        a["key"]: a for a in (await client.get("/api/v1/answers", headers=account["headers"])).json()["items"]
    }
    assert (bank["notice_period"]["answer"], bank["notice_period"]["source"]) == ("90 days", "you")


async def test_the_profile_answers_questions_too(client, account):
    job = await top_job(client, account)
    cand = (await client.get("/api/v1/candidate", headers=account["headers"])).json()
    await client.put(
        "/api/v1/candidate",
        headers=account["headers"],
        json={
            "notice_days": 0,
            "current_ctc": "80 LPA",
            "expected_ctc": "1 Cr",
            "years_experience": 21,
            "version": cand["version"],
        },
    )
    keys = [b["key"] for b in (await readiness(client, account, job["id"]))["blockers"]]
    assert not [k for k in keys if k.startswith("question:")]
    bank = {
        a["key"]: a for a in (await client.get("/api/v1/answers", headers=account["headers"])).json()["items"]
    }
    assert (bank["notice_period"]["answer"], bank["notice_period"]["source"]) == ("Immediate", "profile")
    assert bank["total_experience"]["answer"] == "21 years"


async def test_everything_cleared_makes_the_job_ready(client, account):
    job = await top_job(client, account)
    for b in (await readiness(client, account, job["id"]))["blockers"]:
        if b["kind"] == "question":
            assert (await resolve(client, account, job["id"], b["key"], "An answer")).status_code == 200
        elif b["kind"] == "gap":
            assert (await resolve(client, account, job["id"], b["key"])).status_code == 200
    text = (
        "Chief Engineer for the bank's platforms: cloud, microservices, AI, and teams of 150 engineers. " * 2
    )
    await client.post(
        f"/api/v1/jobs/{job['id']}/description",
        json={"text": text, "version": job["version"]},
        headers=account["headers"],
    )
    r = await readiness(client, account, job["id"])
    assert (r["status"], r["blockers"]) == ("ready", [])

    stats = (await client.get("/api/v1/jobs/stats", headers=account["headers"])).json()
    assert stats["ready"] == 1 and stats["needs_input"] == stats["top"] - 1
    ready = await jobs(client, account, readiness="ready")
    assert [j["id"] for j in ready["items"]] == [job["id"]] and ready["total"] == 1
    assert (await jobs(client, account, readiness="needs_input"))["total"] == stats["needs_input"]


async def test_gaps_are_accepted_per_job(client, account):
    await setup_user(client, account)
    await run_scoring(account)
    top = (await jobs(client, account, tab="top", limit=100))["items"]
    with_gap = None
    for j in top:
        gaps = [b for b in (await readiness(client, account, j["id"]))["blockers"] if b["kind"] == "gap"]
        if gaps:
            with_gap = (j, gaps[0])
            break
    assert with_gap, "expected at least one Top match with a gap"
    j, gap = with_gap
    assert gap["title"].startswith("Gap: ")
    r = await resolve(client, account, j["id"], gap["key"])
    assert gap["key"] not in [b["key"] for b in r.json()["blockers"]]


async def test_a_gap_can_make_a_job_not_a_fit_and_be_undone(client, account):
    job = await top_job(client, account)
    url, h = f"/api/v1/jobs/{job['id']}/not-a-fit", account["headers"]
    r = await client.post(url, json={"gap": "domain"}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["not_a_fit"] == ["domain"] and d["match"]["score"] <= 40 and d["match"]["band"] == "low"
    assert d["readiness"] is None  # no longer a Top match
    assert "not_a_fit" in [p["key"] for p in d["match"]["points_lost"]]
    assert job["id"] not in [j["id"] for j in (await jobs(client, account, tab="top", limit=100))["items"]]
    # A re-score of every job keeps the user's word.
    await run_scoring(account)
    assert (await find(client, account, "Chief Engineer"))["match"]["score"] <= 40

    d = (await client.delete(url, headers=h)).json()
    assert d["not_a_fit"] == [] and d["match"]["band"] == job["match"]["band"]


async def test_not_a_fit_errors(client, account):
    job = await top_job(client, account)
    r = await client.post(
        f"/api/v1/jobs/{job['id']}/not-a-fit", json={"gap": "vibes"}, headers=account["headers"]
    )
    assert (r.status_code, r.json()["error"]["details"][0]["field"]) == (422, "gap")
    missing = "00000000-0000-0000-0000-000000000000"
    r = await client.post(
        f"/api/v1/jobs/{missing}/not-a-fit", json={"gap": "domain"}, headers=account["headers"]
    )
    assert r.status_code == 404


async def test_a_job_in_another_city_asks_about_relocation(client, account):
    # Pune is one of the resumes' places, so the Pune CTO role is a Top match; the candidate lives in Bengaluru.
    await setup_user(client, account, profile=None)
    await set_match_profiles(client, account, locations=["Bengaluru", "Pune"], min_seniority=1)
    cand = (await client.get("/api/v1/candidate", headers=account["headers"])).json()
    await client.put(
        "/api/v1/candidate",
        headers=account["headers"],
        json={"current_location": "Bengaluru", "version": cand["version"]},
    )
    await run_scoring(account)
    pune = await find(client, account, "CTO/Head Technology/Chief Engineering Head")
    blockers = {b["key"]: b for b in (await readiness(client, account, pune["id"]))["blockers"]}
    assert blockers["question:relocation"]["title"] == "Are you willing to relocate to Pune?"
    await resolve(client, account, pune["id"], "question:relocation", "Yes, for the right role")
    assert "question:relocation" not in [
        b["key"] for b in (await readiness(client, account, pune["id"]))["blockers"]
    ]


async def test_no_cover_letter_is_a_blocker(client, account):
    docs = await setup_user(client, account)
    await client.delete(f"/api/v1/cover-letters/{docs['letter']['id']}", headers=account["headers"])
    await run_scoring(account)
    job = await find(client, account, "Chief Engineer")
    assert "cover_letter" in [b["key"] for b in (await readiness(client, account, job["id"]))["blockers"]]


async def test_resolve_errors(client, account):
    job = await top_job(client, account)
    r = await resolve(client, account, job["id"], "question:notice_period", "   ")
    assert (r.status_code, r.json()["error"]["details"][0]["field"]) == (422, "answer")
    assert (await resolve(client, account, job["id"], "description")).json()["error"][
        "code"
    ] == "resolve_elsewhere"
    assert (await resolve(client, account, job["id"], "question:unknown", "x")).status_code == 404

    other = next(j for j in (await jobs(client, account, tab="other"))["items"])
    r = await client.get(f"/api/v1/jobs/{other['id']}/readiness", headers=account["headers"])
    assert (r.status_code, r.json()["error"]["code"]) == (422, "not_a_top_match")
    assert other["readiness"] is None
    missing = "00000000-0000-0000-0000-000000000000"
    assert (
        await client.get(f"/api/v1/jobs/{missing}/readiness", headers=account["headers"])
    ).status_code == 404


# --- Answer bank ----------------------------------------------------------------------------------------


async def test_the_answer_bank_lists_common_questions_first(client, account):
    items = (await client.get("/api/v1/answers", headers=account["headers"])).json()["items"]
    assert [i["key"] for i in items][:4] == [
        "notice_period",
        "current_ctc",
        "expected_ctc",
        "total_experience",
    ]
    assert all(i["standard"] and i["answer"] is None and i["source"] is None for i in items)
    assert [i["required"] for i in items].count(True) == 4


async def test_save_change_and_clear_a_common_answer(client, account):
    h = account["headers"]
    r = await client.put("/api/v1/answers/expected_ctc", json={"answer": "1.2 Cr"}, headers=h)
    assert r.status_code == 200 and (r.json()["answer"], r.json()["version"]) == ("1.2 Cr", 1)
    r = await client.put("/api/v1/answers/expected_ctc", json={"answer": "1.3 Cr", "version": 1}, headers=h)
    assert r.json()["version"] == 2
    stale = await client.put("/api/v1/answers/expected_ctc", json={"answer": "x", "version": 1}, headers=h)
    assert stale.status_code == 409
    assert (await client.delete("/api/v1/answers/expected_ctc", headers=h)).status_code == 204
    bank = {a["key"]: a for a in (await client.get("/api/v1/answers", headers=h)).json()["items"]}
    assert bank["expected_ctc"]["answer"] is None
    assert (await client.delete("/api/v1/answers/expected_ctc", headers=h)).status_code == 404


async def test_your_own_questions(client, account):
    h = account["headers"]
    r = await client.post(
        "/api/v1/answers", json={"question": "Do you have a valid  passport?", "answer": "Yes"}, headers=h
    )
    assert r.status_code == 201
    assert (r.json()["key"], r.json()["question"], r.json()["standard"]) == (
        "do_you_have_a_valid_passport",
        "Do you have a valid passport?",
        False,
    )
    dup = await client.post(
        "/api/v1/answers", json={"question": "Do you have a valid passport", "answer": "No"}, headers=h
    )
    assert dup.status_code == 409
    std = await client.post("/api/v1/answers", json={"question": "Notice period", "answer": "x"}, headers=h)
    assert std.status_code == 409  # same key as a common question
    r = await client.put(
        "/api/v1/answers/do_you_have_a_valid_passport", json={"answer": "Yes, until 2031"}, headers=h
    )
    assert r.json()["answer"] == "Yes, until 2031"
    assert (
        await client.put("/api/v1/answers/never_asked", json={"answer": "x"}, headers=h)
    ).status_code == 404
    assert (
        await client.post("/api/v1/answers", json={"question": "Hi?", "answer": "x"}, headers=h)
    ).status_code == 422
    assert (await client.delete("/api/v1/answers/do_you_have_a_valid_passport", headers=h)).status_code == 204


async def test_old_answers_are_flagged(client, account):
    h = account["headers"]
    await client.put("/api/v1/answers/notice_period", json={"answer": "60 days"}, headers=h)
    async with user_scope(account["id"]) as db:
        await db.execute(update(Answer).values(updated_at=datetime.now(UTC) - timedelta(days=45)))
    bank = {a["key"]: a for a in (await client.get("/api/v1/answers", headers=h)).json()["items"]}
    assert bank["notice_period"]["stale"] is True and bank["current_ctc"]["stale"] is False


async def test_answers_are_private(client, account):
    from tests.conftest import auth, signup

    await client.post(
        "/api/v1/answers",
        json={"question": "Do you have a passport?", "answer": "Yes"},
        headers=account["headers"],
    )
    other = auth((await signup(client))["access_token"])
    client.cookies.clear()
    items = (await client.get("/api/v1/answers", headers=other)).json()["items"]
    assert all(i["standard"] for i in items) and all(i["answer"] is None for i in items)
    assert (await client.delete("/api/v1/answers/do_you_have_a_passport", headers=other)).status_code == 404
    assert (await client.get("/api/v1/answers")).status_code == 401


async def test_company_form_questions_are_answered_from_quick_picks(client, account):
    """The Yes/No questions company forms ask (user, 2026-11-15): listed with their usual answers, saved like
    any answer, and given to the browser extension by key."""
    h = account["headers"]
    items = {i["key"]: i for i in (await client.get("/api/v1/answers", headers=h)).json()["items"]}
    keys = [
        "legally_authorized",
        "sponsorship",
        "work_location",
        "non_compete",
        "confidentiality",
        "under_18",
        "former_government",
        "family_government",
    ]
    assert all(items[k]["choices"] and not items[k]["required"] for k in keys)
    assert items["confidentiality"]["choices"] == ["Yes, I agree", "No"]
    assert items["notice_period"]["choices"] == []
    r = await client.put("/api/v1/answers/sponsorship", json={"answer": "No"}, headers=h)
    assert r.status_code == 200 and r.json()["answer"] == "No"
    fill = await client.get("/api/v1/answers", headers=h)
    assert {i["key"]: i["answer"] for i in fill.json()["items"]}["sponsorship"] == "No"
    bad = await client.put("/api/v1/answers/sponsorship", json={"answer": "  "}, headers=h)
    assert bad.status_code == 422
