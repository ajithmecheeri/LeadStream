"""Scoring the user's jobs: tabs on the Jobs page, match % per resume, suggestions, embeddings, re-scoring."""

import json
from uuid import UUID

import pytest
from sqlalchemy import func, select, text, update

from app.core.config import get_settings
from app.core.db import user_scope
from app.modules.jobs.models import UserJob
from app.modules.llm import gateway
from app.modules.llm.models import LlmCall
from app.modules.matching import service as matching_service
from app.modules.matching.models import JobMatch
from app.modules.matching.service import SCORE, score_user, stale_scores
from app.modules.matching.tasks import rescore_stale_user, score
from tests import samples
from tests.test_ingestion import LINKEDIN, queued_tasks
from tests.test_jobs import NAUKRI, deliver, find, jobs

BENGALURU_VP = {
    "name": "Tech leadership",
    "target_roles": ["Chief Engineer", "Head of Engineering", "CTO"],
    "locations": ["Bengaluru"],
    "work_models": ["Hybrid", "On-site"],
    "min_seniority": 5,
}


async def setup_user(client, account, profile: dict | None = BENGALURU_VP) -> dict:
    """The LinkedIn and Naukri alerts (17 jobs), two resumes, one cover letter and a search profile."""
    h = account["headers"]
    await deliver(client, account, LINKEDIN)
    await deliver(client, account, NAUKRI, dkim_domain="naukri.com")
    cloud = (
        await client.post(
            "/api/v1/resumes", json={"text": samples.RESUME, "label": "Cloud and AI"}, headers=h
        )
    ).json()
    delivery = (
        await client.post(
            "/api/v1/resumes", json={"text": samples.RESUME_DELIVERY, "label": "Delivery"}, headers=h
        )
    ).json()
    letter = (
        await client.post(
            "/api/v1/cover-letters", json={"text": samples.COVER_LETTER, "label": "Tech"}, headers=h
        )
    ).json()
    if profile:
        assert (await client.post("/api/v1/profiles", json=profile, headers=h)).status_code == 201
    return {"cloud": cloud, "delivery": delivery, "letter": letter}


async def run_scoring(account, **kw) -> int:
    async with user_scope(account["id"]) as db:
        return await score_user(db, account["id"], **kw)


async def test_jobs_wait_for_a_resume_before_scoring(client, account):
    await deliver(client, account, LINKEDIN)
    assert await run_scoring(account) == 0
    body = await jobs(client, account, tab="unscored")
    assert body["total"] == 6 and all(j["match"] is None for j in body["items"])
    status = (await client.get("/api/v1/matching/status", headers=account["headers"])).json()
    assert (status["resumes"], status["scored"], status["unscored"], status["ai"]) == (0, 0, 6, False)


async def test_tabs_split_top_matches_from_other_jobs(client, account):
    await setup_user(client, account)
    assert await run_scoring(account) == 17

    top = await jobs(client, account, tab="top")
    other = await jobs(client, account, tab="other")
    assert top["total"] + other["total"] == 17
    assert (await jobs(client, account, tab="unscored"))["total"] == 0

    # Top matches are best first, all strong or good; finance and supply-chain roles are elsewhere.
    scores = [j["match"]["score"] for j in top["items"]]
    assert scores == sorted(scores, reverse=True) and min(scores) >= 70
    top_titles = {j["job"]["title"] for j in top["items"]}
    assert "Chief Engineer" in top_titles
    assert not top_titles & {
        "SEG & India CFO",
        "Head S&OP/SIOP",
        "Director, Finance (FPNA with experience in BI skills required)",
    }

    # Jobs outside the profile's city are ruled out, with the reason.
    pune = next(j for j in other["items"] if j["job"]["location"] == "Pune")
    assert pune["match"]["band"] == "filtered"
    assert pune["match"]["filter_reason"] == "Pune isn't one of your locations"

    stats = (await client.get("/api/v1/jobs/stats", headers=account["headers"])).json()
    assert (stats["top"], stats["other"], stats["unscored"]) == (top["total"], other["total"], 0)


async def test_each_job_scores_every_resume_and_suggests_one(client, account):
    docs = await setup_user(client, account)
    await run_scoring(account)

    chief = await find(client, account, "Chief Architect - Physical AI & Robotics")
    m = chief["match"]
    assert m["primary_score"] is not None and m["provisional"] is True
    assert m["best_resume_label"] == "Cloud and AI" and m["best_is_primary"] is True

    detail = (await client.get(f"/api/v1/jobs/{chief['id']}", headers=account["headers"])).json()["match"]
    assert [r["label"] for r in detail["ranking"]] == ["Cloud and AI", "Delivery"]
    assert detail["ranking"][0]["is_primary"] is True
    assert detail["ranking"][0]["score"] > detail["ranking"][1]["score"]
    assert detail["ranking"][0]["reason"].startswith("Covers")
    assert detail["cover_letter_id"] == docs["letter"]["id"] and detail["cover_letter_label"] == "Tech"
    assert detail["search_profile_name"] == "Tech leadership" and detail["method"] == "rules"
    assert {f["key"] for f in detail["factors"]} >= {"role", "exp", "loc"}


async def test_a_better_variation_is_named_when_it_beats_the_primary(client, account):
    docs = await setup_user(client, account)
    h = account["headers"]
    await client.post(f"/api/v1/resumes/{docs['delivery']['id']}/primary", headers=h)
    await run_scoring(account)
    chief = (await find(client, account, "Chief Architect - Physical AI & Robotics"))["match"]
    assert chief["best_is_primary"] is False and chief["best_resume_label"] == "Cloud and AI"
    assert chief["primary_score"] < chief["score"]


async def test_each_resume_gets_a_match_profile_made_from_it(client, account):
    # User feedback 2026-11-13: no search profile to make by hand; each resume brings its own.
    docs = await setup_user(client, account, profile=None)
    profiles = await match_profiles(client, account)
    assert [p["resume_id"] for p in profiles] == [docs["cloud"]["id"], docs["delivery"]["id"]]
    assert [p["resume_label"] for p in profiles] == ["Cloud and AI", "Delivery"]
    assert all(p["resume_skills"] and p["target_roles"] and p["skills"] == [] for p in profiles)
    await run_scoring(account)
    other = await jobs(client, account, tab="other")
    # Ruled out only by what the resumes say: where the candidate lives, and their level.
    reasons = {j["match"]["filter_reason"] for j in other["items"] if j["match"]["band"] == "filtered"}
    assert all("isn't one of your locations" in r or r.startswith("Below your seniority") for r in reasons)


async def match_profiles(client, account) -> list[dict]:
    r = await client.get("/api/v1/profiles", headers=account["headers"])
    assert r.status_code == 200, r.text
    return [p for p in r.json() if p["resume_id"]]


async def set_match_profiles(client, account, **fields) -> None:
    """Set fields on every resume's match profile (as the user does on the Skill Match Profile tab)."""
    for p in await match_profiles(client, account):
        r = await client.patch(
            f"/api/v1/profiles/{p['id']}",
            headers=account["headers"],
            json={**fields, "version": p["version"]},
        )
        assert r.status_code == 200, r.text


class FakeVoyage:
    model = "voyage-4-lite"

    def __init__(self):
        self.calls: list[list[str]] = []

    async def embed(self, texts, input_type):
        self.calls.append(texts)

        # Two directions: "cloud/AI" text points one way, everything else the other.
        def vec(t: str) -> list[float]:
            ai = any(w in t.lower() for w in ("ai", "cloud", "architect", "engineer"))
            return [1.0, 0.1] + [0.0] * 1022 if ai else [0.1, 1.0] + [0.0] * 1022

        return [vec(t) for t in texts], 10 * len(texts)


@pytest.fixture
def voyage():
    fake = FakeVoyage()
    gateway.use_embedder(fake)
    yield fake
    gateway.use_embedder(None)


async def test_similarity_is_used_and_embeddings_are_reused(client, account, voyage):
    await setup_user(client, account)
    await run_scoring(account)
    assert len(voyage.calls) == 1 and len(voyage.calls[0]) == 2 + 1 + 17  # resumes, letter, jobs in one call

    await run_scoring(account)
    assert len(voyage.calls) == 1  # nothing changed: nothing re-embedded

    async with user_scope(account["id"]) as db:
        (call,) = list(await db.scalars(select(LlmCall)))
    assert (call.provider, call.prompt, call.input_tokens, call.ok) == ("voyage", "embed:matching", 200, True)
    status = (await client.get("/api/v1/matching/status", headers=account["headers"])).json()
    assert status["similarity"] is True


async def test_a_pasted_description_rescores_that_job(client, account, voyage):
    await setup_user(client, account)
    await run_scoring(account)
    chief = await find(client, account, "Chief Engineer")
    text = (
        "Lead platform engineering for core banking on AWS: microservices, Kubernetes and LLM features. " * 2
    )
    r = await client.post(
        f"/api/v1/jobs/{chief['id']}/description",
        json={"text": text, "version": chief["version"]},
        headers=account["headers"],
    )
    assert r.status_code == 200
    (task,) = [
        t
        for t in await queued_tasks()
        if t["task_name"] == "matching.score" and json.loads(t["args"])["user_job_ids"]
    ]
    args = json.loads(task["args"])
    assert args["user_job_ids"] == [chief["id"]] and task["queueing_lock"] is None

    await score(**args)
    assert len(voyage.calls[-1]) == 1 and text.strip() in voyage.calls[-1][0]  # only that job, with its text
    detail = (await client.get(f"/api/v1/jobs/{chief['id']}", headers=account["headers"])).json()
    assert detail["match"]["provisional"] is False
    assert {"cloud", "ai"} <= {f["key"] for f in detail["match"]["factors"]}


async def test_a_failed_alert_keeps_the_new_score_and_a_stale_score_is_swept(client, account, monkeypatch):
    # 2026-11-12: queueing the WhatsApp alert failed after a pasted description's rescore, the whole rescore
    # rolled back and the job kept its title-only score.
    await setup_user(client, account)
    await run_scoring(account)
    chief = await find(client, account, "Chief Engineer")
    r = await client.post(
        f"/api/v1/jobs/{chief['id']}/description",
        json={
            "text": "Lead platform engineering for core banking on AWS and Kubernetes. " * 3,
            "version": chief["version"],
        },
        headers=account["headers"],
    )
    assert r.status_code == 200

    async with user_scope(account["id"]) as db:
        assert [str(i) for i in await stale_scores(db)] == [chief["id"]]  # the rescore hasn't run yet

    async def broken(*a, **kw):
        raise RuntimeError("alert insert failed")

    monkeypatch.setattr(matching_service, "alert_new_matches", broken)
    await run_scoring(account, user_job_ids=[UUID(chief["id"])])
    detail = (await client.get(f"/api/v1/jobs/{chief['id']}", headers=account["headers"])).json()
    assert detail["match"]["provisional"] is False  # the score was kept
    async with user_scope(account["id"]) as db:
        assert await stale_scores(db) == []
    assert await rescore_stale_user(account["id"]) == 0


async def test_the_sweep_queues_a_rescore_for_a_stale_score(client, account):
    await setup_user(client, account)
    await run_scoring(account)
    chief = await find(client, account, "Chief Engineer")
    async with user_scope(account["id"]) as db:
        await db.execute(
            update(UserJob).where(UserJob.id == UUID(chief["id"])).values(description_updated_at=func.now())
        )
        await db.execute(
            update(JobMatch)
            .where(JobMatch.user_job_id == UUID(chief["id"]))
            .values(scored_at=func.now() - text("interval '1 hour'"))
        )
    assert await rescore_stale_user(account["id"]) == 1
    (task,) = [t for t in await queued_tasks() if json.loads(t["args"]).get("reason") == "stale score"]
    assert json.loads(task["args"])["user_job_ids"] == [chief["id"]]


async def test_new_alerts_are_scored_by_the_worker(client, account):
    h = account["headers"]
    await client.post("/api/v1/resumes", json={"text": samples.RESUME}, headers=h)
    await deliver(client, account, LINKEDIN)  # runs the parse task, which queues scoring for that email
    (task,) = [
        t
        for t in await queued_tasks()
        if t["task_name"] == "matching.score" and json.loads(t["args"])["inbound_message_id"]
    ]
    await score(**json.loads(task["args"]))
    assert (await jobs(client, account, tab="unscored"))["total"] == 0


async def test_deleting_every_resume_unscores_the_jobs(client, account):
    docs = await setup_user(client, account)
    await run_scoring(account)
    for d in ("cloud", "delivery"):
        await client.delete(f"/api/v1/resumes/{docs[d]['id']}", headers=account["headers"])
    await run_scoring(account)
    assert (await jobs(client, account, tab="unscored"))["total"] == 17


async def test_rescore_is_queued_once(client, account):
    h = account["headers"]
    for _ in range(2):
        r = await client.post("/api/v1/matching/rescore", headers=h)
        assert (r.status_code, r.json()) == (202, {"queued": True})
    assert len([t for t in await queued_tasks() if t["task_name"] == "matching.score"]) == 1
    assert (await client.get("/api/v1/matching/status", headers=h)).json()["scoring"] is True
    assert (await client.post("/api/v1/matching/rescore")).status_code == 401


async def test_bad_tab_is_refused(client, account):
    r = await client.get("/api/v1/jobs", params={"tab": "best"}, headers=account["headers"])
    assert r.status_code == 422


@pytest.mark.nodb
def test_voyage_requests_stay_under_the_free_tier_token_limit():
    """Without a payment method Voyage allows 10K tokens a minute: a re-score of hundreds of jobs is split."""
    texts = ["x" * 3_000] * 20  # about 1,000 tokens each
    batches = gateway.VoyageEmbedder.batches(texts)
    assert [len(b) for b in batches] == [7, 7, 6]
    assert sum(batches, []) == texts  # same order, nothing lost
    assert [len(b) for b in gateway.VoyageEmbedder.batches(["short"] * 300)] == [128, 128, 44]
    assert gateway.VoyageEmbedder.batches([]) == []


async def test_embeddings_are_spread_over_short_runs(client, account, voyage, monkeypatch):
    """A free-tier Voyage key takes 10K tokens a minute: each run embeds a part, scores with what it has and
    queues the next run, so scores improve step by step instead of one run waiting for an hour."""
    monkeypatch.setattr(get_settings(), "voyage_tokens_per_run", 300)  # about 900 characters a run
    await setup_user(client, account)
    await run_scoring(account)
    assert len(voyage.calls) == 1 and len(voyage.calls[0]) < 20  # a part only
    # A full re-score is waiting to run (queued now, or already queued by the setup: one at a time per user).
    waiting = [t for t in await queued_tasks() if t["task_name"] == SCORE and t["status"] == "todo"]
    assert str(account["id"]) in {json.loads(t["args"])["user_id"] for t in waiting}

    for _ in range(25):  # what the queued runs do, one after another
        await run_scoring(account)
    assert sum(len(c) for c in voyage.calls) == 2 + 1 + 17  # each text embedded once, nothing lost
    calls = len(voyage.calls)
    await run_scoring(account)
    assert len(voyage.calls) == calls  # all done: nothing more to send


async def test_another_resume_can_be_compared_on_a_job(client, account):
    await setup_user(client, account)
    await run_scoring(account)
    item = await find(client, account, "Chief Engineer")
    h, job = account["headers"], f"/api/v1/jobs/{item['id']}"
    match = (await client.get(job, headers=h)).json()["match"]
    best, other = match["ranking"][0], match["ranking"][1]

    r = await client.get(f"{job}/resumes/{other['resume_id']}", headers=h)
    assert r.status_code == 200, r.text
    c = r.json()
    # The same score the ranking shows, with the full breakdown behind it.
    assert (c["label"], c["score"]) == (other["label"], other["score"])
    assert c["factors"] and sum(p["points"] for p in c["points_lost"]) == 100 - c["score"]
    # The suggested resume compares to its own breakdown on the match.
    same = (await client.get(f"{job}/resumes/{best['resume_id']}", headers=h)).json()
    assert same["score"] == match["score"]
    assert {f["key"]: f["score"] for f in same["factors"]} == {f["key"]: f["score"] for f in match["factors"]}

    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"{job}/resumes/{missing}", headers=h)).status_code == 404


@pytest.mark.nodb
async def test_a_full_rescore_commits_in_parts():
    """2026-11-15: scoring all of a user's jobs in one transaction locked their scores and match profile for
    minutes ("Add to match profile" waited behind it). Each part now commits on its own."""
    from uuid import uuid4

    from app.modules.matching.tasks import BATCH, batches

    parts = await batches(uuid4(), [uuid4() for _ in range(BATCH * 2 + 1)])
    assert [len(p) for p in parts] == [BATCH, BATCH, 1]
    assert await batches(uuid4(), []) == [[]]
