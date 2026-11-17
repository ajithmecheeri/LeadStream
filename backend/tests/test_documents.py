"""The resume and cover-letter library, and filling the candidate profile from a resume."""

import base64
import json

import pytest
from sqlalchemy import select

from app.core.db import user_scope
from app.modules.llm import gateway
from app.modules.llm.gateway import Completion
from app.modules.llm.models import LlmCall
from tests import samples
from tests.test_ingestion import queued_tasks


def upload(name: str, data: bytes, **extra) -> dict:
    return {"file_name": name, "content_base64": base64.b64encode(data).decode(), **extra}


async def add_resume(client, account, body: dict, expect: int = 201) -> dict:
    r = await client.post("/api/v1/resumes", json=body, headers=account["headers"])
    assert r.status_code == expect, r.text
    return r.json()


async def resumes(client, account) -> list[dict]:
    r = await client.get("/api/v1/resumes", headers=account["headers"])
    assert r.status_code == 200
    return r.json()["items"]


# --- Resumes ------------------------------------------------------------------------------------------


async def test_upload_a_resume_it_becomes_primary_and_is_scored(client, account):
    body = await add_resume(client, account, upload("Priya_Nair_Resume.docx", samples.docx(samples.RESUME)))
    assert body["label"] == "Priya Nair Resume"
    assert (body["is_primary"], body["source"], body["file_kind"], body["version"]) == (
        True,
        "upload",
        "docx",
        1,
    )
    assert body["text"].startswith("PRIYA NAIR")
    assert body["characters"] == len(body["text"])

    # A re-score of every job is queued, once, a few seconds out (so this request commits first).
    tasks = [t for t in await queued_tasks() if t["task_name"] == "matching.score"]
    assert len(tasks) == 1 and tasks[0]["queueing_lock"] == f"score-all:{account['id']}"
    assert json.loads(tasks[0]["args"])["reason"] == "resume added"

    listed = await resumes(client, account)
    assert [r["label"] for r in listed] == ["Priya Nair Resume"] and "text" not in listed[0]


async def test_every_format_and_pasted_text(client, account):
    await add_resume(client, account, upload("a.pdf", samples.pdf(samples.RESUME_DELIVERY)))
    await add_resume(client, account, upload("b.odt", samples.odt(samples.RESUME)))
    pasted = await add_resume(
        client, account, {"text": samples.RESUME.replace("PRIYA", "P."), "label": "Pasted"}
    )
    assert (pasted["source"], pasted["file_name"], pasted["is_primary"]) == ("paste", None, False)
    assert [r["file_kind"] for r in await resumes(client, account)] == ["pdf", "odt", None]


async def test_one_primary_and_three_variations_at_most(client, account):
    for i in range(4):
        await add_resume(client, account, {"text": samples.RESUME + f"\nVersion {i}", "label": f"v{i}"})
    r = await client.post(
        "/api/v1/resumes", json={"text": samples.RESUME + "\nVersion 5"}, headers=account["headers"]
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "limit_reached"
    assert "up to 3 variations" in r.json()["error"]["message"]


async def test_switch_primary_and_delete_promotes_the_next(client, account):
    a = await add_resume(client, account, {"text": samples.RESUME, "label": "Cloud"})
    b = await add_resume(client, account, {"text": samples.RESUME_DELIVERY, "label": "Delivery"})

    r = await client.post(f"/api/v1/resumes/{b['id']}/primary", headers=account["headers"])
    assert [(x["label"], x["is_primary"]) for x in r.json()["items"]] == [
        ("Delivery", True),
        ("Cloud", False),
    ]

    assert (await client.delete(f"/api/v1/resumes/{b['id']}", headers=account["headers"])).status_code == 204
    (left,) = await resumes(client, account)
    assert (left["id"], left["is_primary"]) == (a["id"], True)


async def test_download_returns_the_original_file(client, account):
    data = samples.docx(samples.RESUME)
    body = await add_resume(client, account, upload("Nair CV.docx", data))
    r = await client.get(f"/api/v1/resumes/{body['id']}/file", headers=account["headers"])
    assert r.status_code == 200 and r.content == data
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert r.headers["content-disposition"] == "attachment; filename*=UTF-8''Nair%20CV.docx"

    pasted = await add_resume(client, account, {"text": samples.RESUME_DELIVERY})
    r = await client.get(f"/api/v1/resumes/{pasted['id']}/file", headers=account["headers"])
    assert r.status_code == 404


async def test_rename_tag_and_link_a_search_profile(client, account):
    body = await add_resume(client, account, {"text": samples.RESUME})
    profile = (
        await client.post(
            "/api/v1/profiles",
            headers=account["headers"],
            json={
                "name": "VP",
                "target_roles": ["VP"],
                "locations": ["Bengaluru"],
                "work_models": ["Hybrid"],
                "min_seniority": 5,
            },
        )
    ).json()
    patch = {
        "label": "  Cloud   and AI ",
        "focus_tags": ["ai", "cloud"],
        "search_profile_id": profile["id"],
        "version": 1,
    }
    r = await client.patch(f"/api/v1/resumes/{body['id']}", json=patch, headers=account["headers"])
    assert r.status_code == 200, r.text
    assert (r.json()["label"], r.json()["focus_tags"], r.json()["version"]) == (
        "Cloud and AI",
        ["ai", "cloud"],
        2,
    )

    stale = await client.patch(
        f"/api/v1/resumes/{body['id']}", json={"label": "x", "version": 1}, headers=account["headers"]
    )
    assert stale.status_code == 409
    cleared = await client.patch(
        f"/api/v1/resumes/{body['id']}",
        json={"search_profile_id": None, "version": 2},
        headers=account["headers"],
    )
    assert cleared.json()["search_profile_id"] is None
    bad = await client.patch(
        f"/api/v1/resumes/{body['id']}",
        json={"search_profile_id": "00000000-0000-0000-0000-000000000000", "version": 3},
        headers=account["headers"],
    )
    assert bad.status_code == 422


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (upload("old.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 200), "unreadable"),
        (upload("scan.pdf", b"%PDF-1.4 nothing readable here"), "unreadable"),
        ({"file_name": "x.docx", "content_base64": "not base64!"}, "unreadable"),
        ({"text": "Too short to be a resume"}, "unreadable"),
        ({"text": samples.RESUME, **upload("x.txt", b"both")}, "validation_error"),
        ({}, "validation_error"),
    ],
)
async def test_bad_uploads_are_refused(client, account, body, code):
    r = await client.post("/api/v1/resumes", json=body, headers=account["headers"])
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == code


async def test_large_and_duplicate_uploads_are_refused(client, account, monkeypatch):
    await add_resume(client, account, {"text": samples.RESUME})
    r = await client.post("/api/v1/resumes", json={"text": samples.RESUME}, headers=account["headers"])
    assert (r.status_code, r.json()["error"]["code"]) == (409, "duplicate")

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "document_max_bytes", 1000)
    r = await client.post(
        "/api/v1/resumes",
        json=upload("big.docx", samples.docx(samples.RESUME_DELIVERY)),
        headers=account["headers"],
    )
    assert (r.status_code, r.json()["error"]["code"]) == (422, "too_large")


async def test_unknown_resume_and_sign_in_required(client, account):
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/api/v1/resumes/{missing}", headers=account["headers"])).status_code == 404
    assert (await client.delete(f"/api/v1/resumes/{missing}", headers=account["headers"])).status_code == 404
    assert (await client.get("/api/v1/resumes")).status_code == 401
    assert (await client.get("/api/v1/cover-letters")).status_code == 401


# --- Cover letters ------------------------------------------------------------------------------------


async def test_cover_letters_default_edit_and_limit(client, account):
    h = account["headers"]
    first = (
        await client.post(
            "/api/v1/cover-letters", json={"text": samples.COVER_LETTER, "label": "Cloud"}, headers=h
        )
    ).json()
    assert first["is_default"] is True
    second = (
        await client.post(
            "/api/v1/cover-letters",
            json=upload("delivery.docx", samples.docx(samples.COVER_LETTER_DELIVERY)),
            headers=h,
        )
    ).json()
    assert (second["label"], second["is_default"], second["file_kind"]) == ("delivery", False, "docx")

    r = await client.post(f"/api/v1/cover-letters/{second['id']}/default", headers=h)
    assert [x["is_default"] for x in r.json()["items"]] == [True, False]

    edited = samples.COVER_LETTER.replace("21 years", "twenty-one years")
    r = await client.patch(
        f"/api/v1/cover-letters/{first['id']}", json={"text": edited, "version": 2}, headers=h
    )
    assert r.status_code == 200 and r.json()["text"] == edited and r.json()["version"] == 3
    r = await client.patch(
        f"/api/v1/cover-letters/{first['id']}", json={"text": "short", "version": 3}, headers=h
    )
    assert r.status_code == 422

    for i in range(3):
        await client.post(
            "/api/v1/cover-letters", json={"text": samples.COVER_LETTER + f" P.S. {i}"}, headers=h
        )
    r = await client.post("/api/v1/cover-letters", json={"text": samples.COVER_LETTER + " P.S. 9"}, headers=h)
    assert (r.status_code, r.json()["error"]["code"]) == (422, "limit_reached")

    assert (await client.delete(f"/api/v1/cover-letters/{second['id']}", headers=h)).status_code == 204
    items = (await client.get("/api/v1/cover-letters", headers=h)).json()["items"]
    assert items[0]["id"] == first["id"] and items[0]["is_default"] is True


# --- Candidate profile from a resume ------------------------------------------------------------------


async def test_fill_the_profile_from_a_resume_by_rules(client, account):
    body = await add_resume(client, account, upload("cv.docx", samples.docx(samples.RESUME)))
    r = await client.post(
        "/api/v1/candidate/from-resume", json={"resume_id": body["id"]}, headers=account["headers"]
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["method"] == "rules"
    assert (d["name"], d["headline"], d["location"], d["years_experience"]) == (
        "Priya Nair",
        "VP, Engineering | Cloud And AI Platforms",
        "Bengaluru, India",
        21,
    )
    assert d["linkedin_url"] == "https://www.linkedin.com/in/priya-nair-example"
    assert len(d["roles"]) == 3 and "Kubernetes" in d["skills"]

    # Nothing is saved until the user reviews and saves.
    assert (await client.get("/api/v1/candidate", headers=account["headers"])).json()["headline"] is None
    cand = (await client.get("/api/v1/candidate", headers=account["headers"])).json()
    save = {
        "headline": d["headline"],
        "summary": d["summary"],
        "current_location": "Bengaluru",
        "years_experience": d["years_experience"],
        "skills": d["skills"],
        "domains": d["domains"],
        "linkedin_url": d["linkedin_url"],
        "version": cand["version"],
    }
    r = await client.put("/api/v1/candidate", json=save, headers=account["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["completeness"] >= 70


class FakeClaude:
    def __init__(self, replies: list[str]):
        self.replies, self.calls = replies, []

    async def complete(self, model, system, user, max_tokens):
        self.calls.append((model, system, json.loads(user)))
        return Completion(self.replies.pop(0), input_tokens=1200, output_tokens=300)


@pytest.fixture
def claude():
    def install(*replies: str) -> FakeClaude:
        fake = FakeClaude(list(replies))
        gateway.use_provider("anthropic", fake)
        return fake

    yield install
    gateway.use_provider("anthropic", None)


async def calls(account) -> list[LlmCall]:
    async with user_scope(account["id"]) as db:
        return list(await db.scalars(select(LlmCall).order_by(LlmCall.id)))


async def test_fill_from_resume_uses_claude_when_configured(client, account, claude):
    fake = claude(
        'Here you go:\n```json\n{"name": "Priya Nair", "headline": "VP Engineering", "years_experience": 21, "skills": ["AWS"]}\n```'
    )
    body = await add_resume(client, account, {"text": samples.RESUME})
    d = (
        await client.post(
            "/api/v1/candidate/from-resume", json={"resume_id": body["id"]}, headers=account["headers"]
        )
    ).json()
    assert (d["method"], d["headline"], d["skills"]) == ("llm", "VP Engineering", ["AWS"])
    model, system, inputs = fake.calls[0]
    assert model == "claude-haiku-5-5" and "Never guess" in system and inputs == {"resume": body["text"]}

    (call,) = await calls(account)
    assert (call.provider, call.prompt, call.prompt_version, call.ok) == (
        "anthropic",
        "resume_extract",
        "v1",
        True,
    )
    assert float(call.cost_usd) == pytest.approx((1200 * 0.10 + 300 * 0.50) / 1e6)


async def test_bad_claude_output_falls_back_to_rules(client, account, claude):
    claude("not json at all", '{"years_experience": "lots"}')
    body = await add_resume(client, account, {"text": samples.RESUME})
    d = (
        await client.post(
            "/api/v1/candidate/from-resume", json={"resume_id": body["id"]}, headers=account["headers"]
        )
    ).json()
    assert d["method"] == "rules" and d["name"] == "Priya Nair"
    assert [(c.ok, (c.error or "")[:25]) for c in await calls(account)] == [
        (False, "invalid output (attempt 1"),
        (False, "invalid output (attempt 2"),
    ]


async def test_the_daily_cost_cap_switches_to_rules(client, account, claude, monkeypatch):
    from app.core.config import get_settings

    claude('{"name": "From Claude"}', '{"name": "From Claude"}')
    monkeypatch.setattr(get_settings(), "llm_daily_cost_cap_usd", 0.0002)
    body = await add_resume(client, account, {"text": samples.RESUME})
    first = (
        await client.post(
            "/api/v1/candidate/from-resume", json={"resume_id": body["id"]}, headers=account["headers"]
        )
    ).json()
    second = (
        await client.post(
            "/api/v1/candidate/from-resume", json={"resume_id": body["id"]}, headers=account["headers"]
        )
    ).json()
    assert (first["method"], second["method"]) == ("llm", "rules")


async def test_fill_from_an_unknown_resume(client, account):
    r = await client.post(
        "/api/v1/candidate/from-resume",
        json={"resume_id": "00000000-0000-0000-0000-000000000000"},
        headers=account["headers"],
    )
    assert r.status_code == 404
