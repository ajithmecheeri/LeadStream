"""Milestone 14.3: pairing the browser extension, what its token can read, and the job portals it never serves."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import update

from app.core.db import user_scope
from app.modules.extension import service
from app.modules.extension.models import ExtensionToken
from tests import samples
from tests.test_apply import PROFILE
from tests.test_duplicates import card, link


@pytest.mark.nodb
def test_codes_carry_their_user_and_only_a_hash_is_kept():
    uid = uuid.uuid4()
    code, digest = service.make(service.CODE_PREFIX, uid)
    assert code.startswith("bmjpair.") and digest not in code
    assert service.parse(service.CODE_PREFIX, code) == (uid, digest)
    assert service.parse(service.TOKEN_PREFIX, code) is None  # a code isn't a token
    assert service.parse(service.CODE_PREFIX, "bmjpair.not-a-user.abc") is None


@pytest.mark.nodb
def test_job_portals_are_blocked_and_company_forms_are_not():
    for url in (
        "https://www.linkedin.com/jobs/view/1",
        "https://in.linkedin.com/jobs/view/2",
        "https://www.naukri.com/job-listings-3",
        "https://in.indeed.com/viewjob?jk=4",
        "https://www.iimjobs.com/j/5",
    ):
        assert service.blocked(url), url
    for url in (
        "https://boards.greenhouse.io/acme/jobs/1",
        "https://jobs.lever.co/acme/2",
        "https://acme.wd1.myworkdayjobs.com/en-US/careers/job/3",
        "https://notlinkedin.com/apply",
        None,
    ):
        assert not service.blocked(url), url


async def paired(client, account) -> dict:
    h = account["headers"]
    r = await client.post("/api/v1/extension/pairing-code", headers=h)
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    r = await client.post("/api/v1/extension/pair", json={"code": code, "name": "Chrome on Windows"})
    assert r.status_code == 200, r.text
    return {"code": code, "headers": {"Authorization": f"Bearer {r.json()['token']}"}}


async def test_a_paired_extension_reads_what_forms_need(client, account):
    h = account["headers"]
    await client.put("/api/v1/apply-profile", json={**PROFILE, "version": 0}, headers=h)
    await client.put("/api/v1/answers/notice_period", json={"answer": "60 days"}, headers=h)
    resume = (
        await client.post("/api/v1/resumes", json={"text": samples.RESUME, "label": "Cloud"}, headers=h)
    ).json()
    (job,) = await link(account["id"], card("VP Engineering", "Acme"))
    ext = await paired(client, account)

    listing = (await client.get(f"/api/v1/jobs/{job}", headers=h)).json()["job"]["sources"][0]["url"]
    page = listing + "?utm_source=email"  # the form's page, as the browser has it
    r = await client.get("/api/v1/extension/fill-data", params={"url": page}, headers=ext["headers"])
    assert r.status_code == 200, r.text
    data = r.json()
    assert (
        data["fields"]["phone"] == "+91 90000 00001" and data["fields"]["current_title"] == "VP, Engineering"
    )
    assert data["fields"]["postal_code"] == "560001"
    assert {a["key"]: a["answer"] for a in data["answers"]}["notice_period"] == "60 days"
    assert data["work_history"][1]["company"] == "Sample Retail Tech"
    assert data["documents"][0]["id"] == resume["id"]
    assert data["job"]["id"] == str(job)

    r = await client.get(f"/api/v1/extension/resumes/{resume['id']}/file", headers=ext["headers"])
    assert r.status_code == 404  # pasted as text: no file to attach
    (device,) = (await client.get("/api/v1/extension/devices", headers=h)).json()
    assert device["name"] == "Chrome on Windows" and device["last_used_at"]


async def test_pairing_codes_are_used_once_and_expire(client, account):
    ext = await paired(client, account)
    r = await client.post("/api/v1/extension/pair", json={"code": ext["code"]})
    assert (r.status_code, r.json()["error"]["code"]) == (400, "invalid_code")
    r = await client.post("/api/v1/extension/pairing-code", headers=account["headers"])
    async with user_scope(account["id"]) as db:
        await db.execute(
            update(ExtensionToken)
            .where(ExtensionToken.token_hash.is_(None))
            .values(pair_expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    r = await client.post("/api/v1/extension/pair", json={"code": r.json()["code"]})
    assert r.status_code == 400
    r = await client.post(
        "/api/v1/extension/pair", json={"code": "bmjpair.nonsense.xxxxxxxxxxxxxxxxxxxxxxxx"}
    )
    assert r.status_code == 400


async def test_the_token_reads_nothing_on_portals_and_stops_when_revoked(client, account):
    ext = await paired(client, account)
    r = await client.get(
        "/api/v1/extension/fill-data",
        params={"url": "https://www.linkedin.com/jobs/view/1"},
        headers=ext["headers"],
    )
    assert (r.status_code, r.json()["error"]["code"]) == (403, "blocked_site")
    assert (await client.get("/api/v1/extension/fill-data")).status_code == 401
    # A user's access token isn't an extension token.
    assert (await client.get("/api/v1/extension/fill-data", headers=account["headers"])).status_code == 401

    (device,) = (await client.get("/api/v1/extension/devices", headers=account["headers"])).json()
    r = await client.delete(f"/api/v1/extension/devices/{device['id']}", headers=account["headers"])
    assert r.status_code == 204
    r = await client.get("/api/v1/extension/fill-data", headers=ext["headers"])
    assert (r.status_code, r.json()["error"]["code"]) == (401, "invalid_token")
    r = await client.delete(f"/api/v1/extension/devices/{device['id']}", headers=account["headers"])
    assert r.status_code == 404
