"""Milestone 6: WhatsApp alerts for strong matches (number verification, which jobs alert, quiet hours, limits)."""

import json
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy import text as sql_text

from app.core.config import get_settings
from app.core.db import user_scope
from app.modules.catalog.models import Job
from app.modules.jobs.models import UserJob
from app.modules.matching.models import JobMatch
from app.modules.notifications import service, tasks, whatsapp
from app.modules.notifications.models import Notification
from app.modules.settings.models import NotificationSettings
from tests import samples
from tests.conftest import PASSWORD, auth, unique_email
from tests.test_ingestion import queued_tasks

WA = "/api/v1/notifications/whatsapp"


@pytest.mark.nodb
def test_numbers_are_read_with_their_country_code():
    assert whatsapp.normalise_number("+91 98765 43210") == "919876543210"
    assert whatsapp.normalise_number("9876543210") == "919876543210"  # an Indian mobile without +91
    assert whatsapp.normalise_number("09876543210") == "919876543210"
    assert whatsapp.normalise_number("0044 7700 900123") == "447700900123"
    assert whatsapp.normalise_number("+1 (415) 555-0100") == "14155550100"
    assert whatsapp.normalise_number("12345") is None
    assert whatsapp.masked("919876543210") == "+91 ••••• 43210"


@pytest.mark.nodb
def test_quiet_hours_hold_messages_until_they_end_on_the_users_clock():
    q = (time(22, 0), time(7, 0))
    ist = "Asia/Kolkata"
    # 23:30 IST: held until 07:00 IST the next morning (01:30 UTC on 6 Nov).
    at = service.quiet_until(datetime(2026, 11, 5, 18, 0, tzinfo=UTC), ist, *q)
    assert at == datetime(2026, 11, 6, 1, 30, tzinfo=UTC)
    # 05:00 IST: held until 07:00 the same morning.
    assert service.quiet_until(datetime(2026, 11, 5, 23, 30, tzinfo=UTC), ist, *q) == datetime(
        2026, 11, 6, 1, 30, tzinfo=UTC
    )
    assert service.quiet_until(datetime(2026, 11, 5, 6, 0, tzinfo=UTC), ist, *q) is None  # 11:30 IST
    assert service.quiet_until(datetime(2026, 11, 5, 6, 0, tzinfo=UTC), ist, None, None) is None
    # Daytime quiet hours (13:00–14:00) don't wrap past midnight.
    assert service.quiet_until(
        datetime(2026, 11, 5, 8, 0, tzinfo=UTC), ist, time(13, 0), time(14, 0)
    ) == datetime(2026, 11, 5, 8, 30, tzinfo=UTC)


async def verified(client, account, monkeypatch) -> None:
    monkeypatch.setattr(service, "new_code", lambda: "123456")
    r = await client.post(f"{WA}/number", json={"number": "+91 98765 43210"}, headers=account["headers"])
    assert r.status_code == 200 and r.json()["code_sent"] is True
    r = await client.post(f"{WA}/verify", json={"code": "123456"}, headers=account["headers"])
    assert r.status_code == 200 and r.json()["verified"] is True


async def add_job(user_id: UUID, title: str, band: str = "strong", score: int = 90, **uj) -> UUID:
    async with user_scope(user_id) as db:
        job = Job(title=title, company="Acme Cloud", location="Bengaluru")
        db.add(job)
        await db.flush()
        row = UserJob(user_id=user_id, job_id=job.id, lead="alert", **uj)
        db.add(row)
        await db.flush()
        db.add(JobMatch(user_job_id=row.id, user_id=user_id, band=band, score=score))
        return row.id


async def outbox(user_id: UUID) -> list[Notification]:
    async with user_scope(user_id) as db:
        return list(await db.scalars(select(Notification).order_by(Notification.created_at)))


async def alert(user_id: UUID, ids: list[UUID], now: datetime | None = None) -> int:
    async with user_scope(user_id) as db:
        return await service.alert_new_matches(db, user_id, ids, now)


async def no_quiet_hours(user_id: UUID) -> None:
    async with user_scope(user_id) as db:
        ns = await db.get(NotificationSettings, user_id)
        ns.quiet_start = ns.quiet_end = None


async def test_a_number_is_verified_with_a_code_sent_on_whatsapp(client, account, monkeypatch):
    h = account["headers"]
    monkeypatch.setattr(service, "new_code", lambda: "123456")
    start = (await client.get(WA, headers=h)).json()
    assert start["number"] is None and start["verified"] is False and start["configured"] is False

    bad = await client.post(f"{WA}/number", json={"number": "12345 67"}, headers=h)
    assert bad.status_code == 422 and bad.json()["error"]["details"][0]["field"] == "number"

    sent = (await client.post(f"{WA}/number", json={"number": "98765 43210"}, headers=h)).json()
    assert sent["number"] == "+91 ••••• 43210" and sent["code_sent"] and not sent["verified"]
    # No WhatsApp keys locally: the code goes to the worker log, and the message is listed as logged.
    assert [(n["kind"], n["status"]) for n in sent["recent"]] == [("code", "logged")]
    assert "123456" not in sent["recent"][0]["body"]

    again = await client.post(f"{WA}/number", json={"number": "98765 43210"}, headers=h)
    assert again.status_code == 429  # one code a minute

    wrong = await client.post(f"{WA}/verify", json={"code": "000000"}, headers=h)
    assert wrong.status_code == 422
    ok = (await client.post(f"{WA}/verify", json={"code": "123456"}, headers=h)).json()
    assert ok["verified"] and not ok["code_sent"] and ok["jobs"]
    used = await client.post(f"{WA}/verify", json={"code": "123456"}, headers=h)
    assert used.status_code == 409 and used.json()["error"]["code"] == "no_code"


async def test_a_code_stops_working_after_five_wrong_tries(client, account, monkeypatch):
    h = account["headers"]
    monkeypatch.setattr(service, "new_code", lambda: "123456")
    await client.post(f"{WA}/number", json={"number": "9876543210"}, headers=h)
    for _ in range(service.CODE_TRIES):
        assert (await client.post(f"{WA}/verify", json={"code": "111111"}, headers=h)).status_code == 422
    r = await client.post(f"{WA}/verify", json={"code": "123456"}, headers=h)
    assert r.status_code == 409 and r.json()["error"]["code"] == "code_expired"


async def test_strong_new_matches_alert_once_and_others_do_not(client, account, monkeypatch):
    uid = account["id"]
    await verified(client, account, monkeypatch)
    await no_quiet_hours(uid)
    strong = await add_job(uid, "VP Engineering")
    good = await add_job(uid, "Director of Engineering", band="good", score=78)
    applied = await add_job(uid, "Head of Platform", status="applied")
    old = await add_job(uid, "CTO", first_seen_at=datetime.now(UTC) - timedelta(days=3))

    assert await alert(uid, [strong, good, applied, old]) == 1
    assert await alert(uid, [strong]) == 0  # seen again (a re-score, a later email): no second message
    [n] = [n for n in await outbox(uid) if n.kind == "new_job"]
    assert (n.user_job_id, n.status) == (strong, "queued")
    assert n.body == "Top match, 90%: VP Engineering at Acme Cloud."
    assert any(t["task_name"] == service.SEND for t in await queued_tasks())

    assert await tasks.send(uid, n.id) == "logged"  # no keys: written to the log
    [n] = [n for n in await outbox(uid) if n.kind == "new_job"]
    assert n.sent_at is not None and n.error is None


async def test_the_alert_insert_works_with_a_generic_plan(client, account, monkeypatch):
    # 2026-11-12: after five runs the worker's prepared insert used a generic plan, the partial unique index no
    # longer matched its ON CONFLICT, and the error rolled back the rescore of a pasted description.
    uid = account["id"]
    await verified(client, account, monkeypatch)
    await no_quiet_hours(uid)
    strong = await add_job(uid, "VP Engineering")
    async with user_scope(uid) as db:
        await db.execute(sql_text("set local plan_cache_mode = force_generic_plan"))
        assert await service.alert_new_matches(db, uid, [strong]) == 1
        assert await service.alert_new_matches(db, uid, [strong]) == 0


async def test_scoring_queues_the_alert(client, account, monkeypatch):
    """The hook in score_user: a job that scores strong right after it arrives is alerted."""
    uid = account["id"]
    await verified(client, account, monkeypatch)
    await no_quiet_hours(uid)
    calls = []

    async def fake(db, user_id, ids, now=None):
        calls.append(ids)
        return 0

    from app.modules.matching import service as matching

    monkeypatch.setattr(matching, "alert_new_matches", fake)
    await client.post("/api/v1/resumes", json={"text": samples.RESUME}, headers=account["headers"])
    job = await add_job(uid, "VP Engineering")
    async with user_scope(uid) as db:
        await matching.score_user(db, uid, [job])
    assert calls == [[job]]


async def test_alerts_wait_for_quiet_hours_and_stop_at_the_daily_limit(client, account, monkeypatch):
    uid = account["id"]
    await verified(client, account, monkeypatch)
    async with user_scope(uid) as db:
        ns = await db.get(NotificationSettings, uid)
        ns.quiet_start, ns.quiet_end, ns.max_push_per_day = time(22, 0), time(7, 0), 2
    jobs = [await add_job(uid, f"VP Engineering {i}", score=90 - i) for i in range(3)]
    night = datetime.now(UTC).replace(hour=18, minute=0, second=0, microsecond=0)  # 23:30 IST
    assert await alert(uid, jobs, now=night) == 2
    by_job = {n.user_job_id: n for n in await outbox(uid) if n.kind == "new_job"}
    assert [by_job[j].status for j in jobs] == ["held", "held", "skipped"]  # best two kept, at most 2 a day
    assert by_job[jobs[0]].send_after == night.replace(hour=1, minute=30) + timedelta(days=1)
    assert by_job[jobs[2]].error == "Daily limit reached (2 a day)"


async def test_messages_logged_before_whatsapp_was_set_up_dont_use_up_the_limit(client, account, monkeypatch):
    uid = account["id"]
    await verified(client, account, monkeypatch)
    await no_quiet_hours(uid)
    a = await add_job(uid, "VP Engineering")
    await alert(uid, [a])
    async with user_scope(uid) as db:
        for n in await db.scalars(select(Notification).where(Notification.kind == "new_job")):
            n.status = "logged"  # written to the log: WhatsApp wasn't set up yet
        assert await service.sent_today(db, "Asia/Kolkata", datetime.now(UTC)) == 1
        monkeypatch.setattr(get_settings(), "whatsapp_phone_number_id", "1234")
        monkeypatch.setattr(get_settings(), "whatsapp_access_token", "token")
        assert await service.sent_today(db, "Asia/Kolkata", datetime.now(UTC)) == 0


async def test_a_held_alert_is_dropped_if_the_user_applies_or_turns_alerts_off(client, account, monkeypatch):
    uid, h = account["id"], account["headers"]
    await verified(client, account, monkeypatch)
    await no_quiet_hours(uid)
    a, b = await add_job(uid, "VP Engineering"), await add_job(uid, "VP Platform")
    await alert(uid, [a, b])
    async with user_scope(uid) as db:
        (await db.get(UserJob, a)).status = "applied"
    na, nb = sorted((n for n in await outbox(uid) if n.kind == "new_job"), key=lambda n: n.user_job_id != a)
    assert await tasks.send(uid, na.id) == "skipped"
    assert (await client.patch(WA, json={"jobs": False}, headers=h)).json()["jobs"] is False
    assert await tasks.send(uid, nb.id) == "skipped"
    errors = {n.user_job_id: n.error for n in await outbox(uid)}
    assert errors[a] == "You already acted on this job" and errors[b] == "WhatsApp job alerts were turned off"


async def test_meta_is_called_with_the_approved_template(client, account, monkeypatch):
    uid = account["id"]
    monkeypatch.setattr(get_settings(), "whatsapp_phone_number_id", "1234")
    monkeypatch.setattr(get_settings(), "whatsapp_access_token", "token")
    seen = []

    def meta(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 3:
            return httpx.Response(
                400, json={"error": {"message": "Recipient phone number not in allowed list"}}
            )
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{len(seen)}"}]})

    real = httpx.AsyncClient
    monkeypatch.setattr(whatsapp.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(meta)))
    await verified(client, account, monkeypatch)
    await no_quiet_hours(uid)
    job = await add_job(uid, "VP Engineering")
    await alert(uid, [job])
    [n] = [n for n in await outbox(uid) if n.kind == "new_job"]
    assert await tasks.send(uid, n.id) == "sent"

    code, msg = [json.loads(r.content) for r in seen]
    assert seen[0].url.path == "/v21.0/1234/messages" and seen[0].headers["authorization"] == "Bearer token"
    assert code["template"]["name"] == "verify_code" and code["to"] == "919876543210"
    assert code["template"]["components"][0]["parameters"] == [{"type": "text", "text": "123456"}]
    assert msg["template"]["name"] == "job_alert"
    params = [p["text"] for p in msg["template"]["components"][0]["parameters"]]
    assert params == ["VP Engineering", "Acme Cloud", "90", f"{get_settings().public_base_url}/jobs/{job}"]

    # Meta refuses (number not on the test list): the user sees why; nothing is retried.
    r = await client.post(f"{WA}/test", headers=account["headers"])
    assert r.status_code == 502 and "allowed list" in r.json()["error"]["message"]


async def test_a_test_message_needs_a_verified_number_and_a_match(client, account, monkeypatch):
    h = account["headers"]
    assert (await client.post(f"{WA}/test", headers=h)).json()["error"]["code"] == "not_verified"
    await verified(client, account, monkeypatch)
    assert (await client.post(f"{WA}/test", headers=h)).json()["error"]["code"] == "no_match"
    await add_job(account["id"], "Director of Engineering", band="good", score=80)
    sent = (await client.post(f"{WA}/test", headers=h)).json()
    assert (sent["kind"], sent["status"]) == ("test", "logged")
    assert sent["body"] == "Top match, 80%: Director of Engineering at Acme Cloud."


async def test_removing_the_number_drops_waiting_messages(client, account, monkeypatch):
    uid, h = account["id"], account["headers"]
    await verified(client, account, monkeypatch)
    await alert(
        uid,
        [await add_job(uid, "VP Engineering")],
        now=datetime.now(UTC).replace(hour=18, minute=0, second=0),
    )
    assert (await client.delete(WA, headers=h)).status_code == 204
    out = (await client.get(WA, headers=h)).json()
    assert out["number"] is None and not out["verified"]
    assert [n["error"] for n in out["recent"] if n["kind"] == "new_job"] == ["WhatsApp number removed"]


async def test_a_number_given_at_sign_up_is_saved_and_verified_later(client, monkeypatch):
    body = {
        "email": unique_email(),
        "first_name": "Meera",
        "last_name": "Das",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
        "accept_terms": True,
        "job_locations": ["Bengaluru"],
    }
    bad = await client.post("/api/v1/auth/signup", json=body | {"whatsapp_number": "12345"})
    assert bad.status_code == 422 and bad.json()["error"]["details"][0]["field"] == "whatsapp_number"

    r = await client.post("/api/v1/auth/signup", json=body | {"whatsapp_number": "+91 98765 43210"})
    assert r.status_code == 201
    client.cookies.clear()
    h = auth(r.json()["access_token"])
    saved = (await client.get(WA, headers=h)).json()
    # Saved, but nothing sent until the user asks for a code: no message at sign-up.
    assert saved["number"] == "+91 ••••• 43210" and not saved["verified"] and not saved["code_sent"]
    assert saved["recent"] == []

    monkeypatch.setattr(service, "new_code", lambda: "123456")
    sent = (await client.post(f"{WA}/code", headers=h)).json()
    assert sent["code_sent"] and sent["recent"][0]["kind"] == "code"
    ok = (await client.post(f"{WA}/verify", json={"code": "123456"}, headers=h)).json()
    assert ok["verified"]
    again = await client.post(f"{WA}/code", headers=h)
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_verified"


async def test_a_code_needs_a_saved_number(client, account):
    r = await client.post(f"{WA}/code", headers=account["headers"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_number"
