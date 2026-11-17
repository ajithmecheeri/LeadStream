"""Receiving alert emails (/internal/inbound), parsing them into the user's jobs, and the mail/inbox views."""

import base64
import json
import time
from email.message import EmailMessage
from pathlib import Path
from uuid import UUID

import asyncpg
import pytest
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import sessionmaker, user_scope
from app.modules.catalog.models import Job
from app.modules.catalog.parsers.registry import load
from app.modules.ingestion import service
from app.modules.ingestion.models import InboundRaw
from app.modules.ingestion.service import sign
from app.modules.ingestion.tasks import parse_alert
from app.modules.jobs.models import UserJob
from tests.conftest import auth, signup
from tests.test_isolation import _dsn

EMAILS = Path(__file__).parent / "fixtures" / "emails"
LINKEDIN = (EMAILS / "linkedin-alert-vice-president-bangalore-2026-10-29.eml").read_bytes()
INVITE = (EMAILS / "naukri-recruiter-invite-vp-ai-2026-09-18.eml").read_bytes()


def payload(raw: bytes, recipient: str, dkim_domain: str = "linkedin.com", result: str = "pass") -> dict:
    return {
        "recipient": recipient,
        "dkim": [{"domain": dkim_domain, "result": result}],
        "raw_mime_base64": base64.b64encode(raw).decode(),
    }


async def post_inbound(client, body: dict, ts: int | None = None, secret: str | None = None):
    data = json.dumps(body).encode()
    stamp = str(ts if ts is not None else int(time.time()))
    sig = sign(secret or get_settings().inbound_hmac_secret, stamp, data)
    return await client.post(
        "/internal/inbound",
        content=data,
        headers={"content-type": "application/json", "x-timestamp": stamp, "x-signature": sig},
    )


async def queued_tasks() -> list[dict]:
    conn = await asyncpg.connect(_dsn(get_settings().database_url))
    try:
        rows = await conn.fetch(
            "select task_name, args, status, queueing_lock from procrastinate_jobs order by id"
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def user_jobs(user_id: UUID) -> list[UserJob]:
    async with user_scope(user_id) as db:
        return list((await db.execute(select(UserJob).order_by(UserJob.first_seen_at))).scalars())


# --- Receiving ---------------------------------------------------------------------------------------


async def test_alert_is_stored_queued_and_parsed_into_the_users_jobs(client, account):
    r = await post_inbound(client, payload(LINKEDIN, account["address"]))
    assert r.status_code == 202, r.text
    message_id = r.json()["inbound_message_id"]

    (task,) = await queued_tasks()
    assert task["task_name"] == "ingestion.parse_alert" and task["status"] == "todo"
    inbox = (await client.get("/api/v1/inbox/messages", headers=account["headers"])).json()
    assert [(m["id"], m["status"], m["sender"]) for m in inbox] == [
        (message_id, "accepted", "jobalerts-noreply@linkedin.com")
    ]

    await parse_alert(**json.loads(task["args"]))  # what the worker runs

    (msg,) = (await client.get("/api/v1/inbox/messages", headers=account["headers"])).json()
    assert (msg["status"], msg["cards_found"], msg["parser"]) == ("parsed", 6, "linkedin_digest@1")
    assert msg["alert_name"] == "vice president in Bangalore Urban"
    jobs = await user_jobs(account["id"])
    assert len(jobs) == 6 and {j.status for j in jobs} == {"new"}
    # Lines about the user ("2 connections") are stored on the user's own row.
    assert {"card_lines": ["2 connections"]} in [j.card_details for j in jobs]


async def test_parsing_again_keeps_the_users_choices(client, account):
    r = await post_inbound(client, payload(LINKEDIN, account["address"]))
    args = json.loads((await queued_tasks())[0]["args"])
    await parse_alert(**args)
    async with user_scope(account["id"]) as db:
        await db.execute(update(UserJob).values(status="ignored"))

    await parse_alert(**args)

    jobs = await user_jobs(account["id"])
    assert len(jobs) == 6 and {j.status for j in jobs} == {"ignored"}
    assert r.status_code == 202


async def test_recruiter_invite_keeps_the_private_apply_link_on_the_users_row(client, account):
    r = await post_inbound(client, payload(INVITE, account["address"], dkim_domain="naukri.com"))
    assert r.status_code == 202
    await parse_alert(**json.loads((await queued_tasks())[0]["args"]))

    (job,) = await user_jobs(account["id"])
    assert job.lead == "recruiter_invite" and "applyBroadcastMail" in job.apply_url


async def test_the_same_email_twice_is_a_duplicate(client, account):
    assert (await post_inbound(client, payload(LINKEDIN, account["address"]))).status_code == 202
    r = await post_inbound(client, payload(LINKEDIN, account["address"]))
    assert (r.status_code, r.json()) == (
        200,
        {"accepted": False, "inbound_message_id": None, "reason": "duplicate"},
    )
    assert len(await queued_tasks()) == 1


async def test_an_unrecognised_email_from_a_portal_is_kept_as_unparsed(client, account):
    msg = EmailMessage()
    msg["From"], msg["Subject"], msg["Message-ID"] = (
        "LinkedIn <messages-noreply@linkedin.com>",
        "New message",
        "<m@x>",
    )
    msg.set_content("Someone sent you a message")
    assert (await post_inbound(client, payload(msg.as_bytes(), account["address"]))).status_code == 202

    await parse_alert(**json.loads((await queued_tasks())[0]["args"]))

    (m,) = (await client.get("/api/v1/inbox/messages", headers=account["headers"])).json()
    assert (m["status"], m["cards_found"]) == ("unparsed", 0)
    assert await user_jobs(account["id"]) == []


async def test_email_is_kept_even_if_queueing_fails(client, account, monkeypatch):
    async def broken_defer(*_, **__):
        raise ConnectionError("queue down")

    monkeypatch.setattr(service, "defer", broken_defer)
    r = await post_inbound(client, payload(LINKEDIN, account["address"]))

    assert r.status_code == 202  # stored; the periodic sweep queues it later
    (m,) = (await client.get("/api/v1/inbox/messages", headers=account["headers"])).json()
    assert m["status"] == "accepted"


# --- Rejections --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ts,secret,message",
    [
        (None, "wrong-secret", "Signature does not match"),
        (int(time.time()) - 3600, None, "Signature timestamp is too old or in the future"),
    ],
)
async def test_bad_signature_is_refused(client, account, ts, secret, message):
    r = await post_inbound(client, payload(LINKEDIN, account["address"]), ts=ts, secret=secret)
    assert r.status_code == 401
    assert (r.json()["error"]["code"], r.json()["error"]["message"]) == ("bad_signature", message)
    assert await queued_tasks() == []


async def test_missing_signature_is_refused(client, account):
    r = await client.post("/internal/inbound", json=payload(LINKEDIN, account["address"]))
    assert r.status_code == 401 and r.json()["error"]["code"] == "bad_signature"


async def test_inbound_is_off_without_a_secret(client, account, monkeypatch):
    monkeypatch.setattr(get_settings(), "inbound_hmac_secret", "")
    r = await post_inbound(client, payload(LINKEDIN, account["address"]), secret="anything")
    assert r.status_code == 503 and r.json()["error"]["code"] == "inbound_disabled"


@pytest.mark.parametrize(
    "recipient",
    ["alerts-nosuchtoken@in.fitfirst.local", "someone@example.com", "alerts-{token}@other-domain.com"],
)
async def test_unknown_recipient_is_dropped(client, account, recipient):
    token = account["address"].split("@")[0].removeprefix("alerts-")
    r = await post_inbound(client, payload(LINKEDIN, recipient.format(token=token)))
    assert (r.status_code, r.json()["reason"]) == (200, "unknown_recipient")


@pytest.mark.parametrize(
    "from_addr,dkim_domain,result",
    [
        ("jobalerts-noreply@linkedin.com", "linkedin.com", "fail"),  # DKIM failed: possibly forged
        ("jobalerts-noreply@linkedin.com", "evil.com", "pass"),  # DKIM passed for another domain
        ("friend@gmail.com", "gmail.com", "pass"),  # not a job portal
        ("someone@google.com", "google.com", "pass"),  # Google, but not the forwarding service
    ],
)
async def test_sender_must_be_an_allowed_portal_with_dkim(client, account, from_addr, dkim_domain, result):
    raw = LINKEDIN.replace(b"LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>", from_addr.encode())
    r = await post_inbound(client, payload(raw, account["address"], dkim_domain=dkim_domain, result=result))
    assert (r.status_code, r.json()["reason"]) == (200, "sender_not_allowed")
    assert (await client.get("/api/v1/inbox/messages", headers=account["headers"])).json() == []


async def test_oversized_email_is_refused(client, account, monkeypatch):
    monkeypatch.setattr(get_settings(), "inbound_max_bytes", 1000)
    r = await post_inbound(client, payload(LINKEDIN, account["address"]))
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"


async def test_invalid_payload_is_refused(client):
    r = await post_inbound(client, {"recipient": "x"})  # signed, but no email in it
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


# --- Gmail forwarding setup ----------------------------------------------------------------------------


def gmail_confirmation() -> bytes:
    # Built from Google's documented format; replace with a real sample when one is available.
    msg = EmailMessage()
    msg["From"] = "Gmail Team <forwarding-noreply@google.com>"
    msg["Subject"] = "(#123456789) Gmail Forwarding Confirmation - Receive Mail from someone@gmail.com"
    msg["Message-ID"] = "<confirm-1@google.com>"
    msg.set_content("someone@gmail.com has requested to automatically forward mail to your email address.")
    return msg.as_bytes()


async def test_mail_shows_the_address_and_gmail_confirmation_code(client, account):
    before = (await client.get("/api/v1/mail", headers=account["headers"])).json()
    assert before == {
        "address": account["address"],
        "forward_senders": [],
        "receiving": False,
        "last_received_at": None,
        "forwarding_code": None,
        "forwarding_link": None,
        "forwarding_code_at": None,
        "upload_enabled": False,
    }

    r = await post_inbound(
        client, payload(gmail_confirmation(), account["address"], dkim_domain="google.com")
    )
    assert r.status_code == 202

    after = (await client.get("/api/v1/mail", headers=account["headers"])).json()
    assert after["receiving"] is True and after["forwarding_code"] == "123456789"
    assert await queued_tasks() == []  # nothing to parse


CONFIRM = "https://mail-settings.google.com/mail/vf-%5BAbC123%5D-xYz_45-Q9"


def gmail_link_confirmation() -> bytes:
    # The form Gmail sent on 2026-11-03 (shortened, fictional addresses and link): a link instead of a code.
    msg = EmailMessage()
    msg["From"] = '"Gmail Team" <forwarding-noreply@google.com>'
    msg["Subject"] = "(Gmail Forwarding Confirmation - Receive Mail from someone@gmail.com"
    msg["Message-ID"] = "<confirm-2@google.com>"
    msg.set_content(
        "someone@gmail.com has requested to automatically forward mail to\nyour email\naddress x.\n\n"
        "To allow someone@gmail.com to automatically forward mail to your address,\n"
        f"please click the link below to confirm the request:\n\n{CONFIRM}\n\n"
        "...click this link to cancel this\nverification:\n"
        "https://mail-settings.google.com/mail/uf-%5BAbC123%5D-xYz_45-Q9\n"
    )
    return msg.as_bytes()


async def test_mail_shows_gmails_confirmation_link(client, account):
    r = await post_inbound(
        client, payload(gmail_link_confirmation(), account["address"], dkim_domain="google.com")
    )
    assert r.status_code == 202

    after = (await client.get("/api/v1/mail", headers=account["headers"])).json()
    assert after["forwarding_link"] == CONFIRM  # the confirm link, not the cancel one
    assert after["forwarding_code"] is None and after["forwarding_code_at"] is not None
    assert await queued_tasks() == []


async def test_a_confirmation_link_from_anyone_but_google_is_ignored(client, account):
    fake = gmail_link_confirmation().replace(b"forwarding-noreply@google.com", b"noreply@linkedin.com")
    r = await post_inbound(client, payload(fake, account["address"]))
    assert r.status_code == 202
    assert (await client.get("/api/v1/mail", headers=account["headers"])).json()["forwarding_link"] is None


async def test_rotating_the_address_retires_the_old_one(client, account):
    r = await client.post("/api/v1/mail/address/rotate", headers=account["headers"])
    assert r.status_code == 200
    new = r.json()["address"]
    assert new != account["address"] and new.startswith("alerts-")

    old = await post_inbound(client, payload(LINKEDIN, account["address"]))
    assert old.json()["reason"] == "unknown_recipient"
    assert (await post_inbound(client, payload(LINKEDIN, new))).status_code == 202


async def test_mail_and_inbox_need_sign_in(client):
    for method, path in [
        ("get", "/api/v1/mail"),
        ("post", "/api/v1/mail/address/rotate"),
        ("get", "/api/v1/inbox/messages"),
    ]:
        r = await getattr(client, method)(path)
        assert r.status_code == 401, path


async def test_inbox_is_private_to_each_user(client, account):
    other = await signup(client, name="Bob")
    client.cookies.clear()
    await post_inbound(client, payload(LINKEDIN, account["address"]))

    assert (await client.get("/api/v1/inbox/messages", headers=auth(other["access_token"]))).json() == []
    assert len((await client.get("/api/v1/inbox/messages", headers=account["headers"])).json()) == 1


async def test_inbox_pages_with_limit_and_before(client, account):
    for _ in range(3):
        body = payload(LINKEDIN, account["address"])
        body["message_id"] = f"<{time.time_ns()}@x>"
        await post_inbound(client, body)
    first = (await client.get("/api/v1/inbox/messages?limit=2", headers=account["headers"])).json()
    rest = (
        await client.get(
            "/api/v1/inbox/messages", params={"before": first[-1]["received_at"]}, headers=account["headers"]
        )
    ).json()
    assert len(first) == 2 and len(rest) == 1
    bad = await client.get("/api/v1/inbox/messages?limit=0", headers=account["headers"])
    assert bad.status_code == 422


async def test_the_raw_email_is_kept_privately_for_reparsing(client, account):
    await post_inbound(client, payload(LINKEDIN, account["address"]))

    async with user_scope(account["id"]) as db:
        (raw,) = (await db.execute(select(InboundRaw))).scalars().all()
    assert raw.body == LINKEDIN


# --- Hand forwards from the user's own addresses (Mail setup) -------------------------------------------------


def hand_forward(by: str) -> bytes:
    msg = EmailMessage()
    msg["From"], msg["Subject"], msg["Message-ID"] = by, "Fwd: VP jobs", "<fwd-1@mail.gmail.com>"
    block = "---------- Forwarded message ---------\nFrom: LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>\n\n"
    linkedin = (EMAILS / "linkedin-alert-vice-president-bangalore-2026-10-29.eml").read_bytes()
    msg.set_content(block + load(linkedin).get_body(("plain",)).get_content())
    return msg.as_bytes()


async def test_a_hand_forward_is_refused_unless_its_sender_is_on_the_users_list(client, account):
    raw = hand_forward("Tester <tester@gmail.com>")
    r = await post_inbound(client, payload(raw, account["address"], dkim_domain="gmail.com"))
    assert r.json()["reason"] == "sender_not_allowed"

    # Another user listing the address doesn't help: the list is per user.
    other = await signup(client, email="other-forwarder@example.com")
    client.cookies.clear()
    r = await client.post(
        "/api/v1/mail/senders", headers=auth(other["access_token"]), json={"address": "tester@gmail.com"}
    )
    assert r.status_code == 201
    r = await post_inbound(client, payload(raw, account["address"], dkim_domain="gmail.com"))
    assert r.json()["reason"] == "sender_not_allowed"

    r = await client.post(
        "/api/v1/mail/senders", headers=account["headers"], json={"address": "Tester@Gmail.com"}
    )
    assert r.status_code == 201 and r.json()["address"] == "tester@gmail.com"
    forged = await post_inbound(
        client, payload(raw, account["address"], dkim_domain="gmail.com", result="fail")
    )
    assert forged.json()["reason"] == "sender_not_allowed"  # DKIM must still pass

    r = await post_inbound(client, payload(raw, account["address"], dkim_domain="gmail.com"))
    assert r.status_code == 202
    await parse_alert(**json.loads((await queued_tasks())[0]["args"]))
    (msg,) = (await client.get("/api/v1/inbox/messages", headers=account["headers"])).json()
    assert (msg["status"], msg["cards_found"]) == ("parsed", 6)

    # The forwarded jobs are unverified in the shared catalog; the same jobs in a real alert verify them.
    async with sessionmaker()() as db:
        assert {j.verified for j in await db.scalars(select(Job))} == {False}
    await post_inbound(client, payload(LINKEDIN, account["address"]))
    await parse_alert(**json.loads((await queued_tasks())[-1]["args"]))
    async with sessionmaker()() as db:
        assert {j.verified for j in await db.scalars(select(Job))} == {True}


async def test_forwarding_addresses_can_be_listed_added_and_removed(client, account):
    h = account["headers"]
    added = await client.post("/api/v1/mail/senders", headers=h, json={"address": "me@yahoo.com"})
    assert added.status_code == 201
    assert [
        s["address"] for s in (await client.get("/api/v1/mail", headers=h)).json()["forward_senders"]
    ] == ["me@yahoo.com"]
    r = await client.delete(f"/api/v1/mail/senders/{added.json()['id']}", headers=h)
    assert r.status_code == 204
    assert (await client.get("/api/v1/mail", headers=h)).json()["forward_senders"] == []


async def test_forwarding_addresses_are_checked(client, account):
    h = account["headers"]

    async def add(address):
        return await client.post("/api/v1/mail/senders", headers=h, json={"address": address})

    assert (await add("not an email")).status_code == 422
    for portal in (
        "jobalerts-noreply@linkedin.com",
        "naukrialerts@naukri.com",
        "forwarding-noreply@google.com",
    ):
        r = await add(portal)
        assert (r.status_code, r.json()["error"]["code"]) == (422, "not_your_address"), portal
    r = await add(f"x@{get_settings().inbound_domain}")
    assert r.json()["error"]["code"] == "not_your_address"
    for n in range(3):
        assert (await add(f"me{n}@gmail.com")).status_code == 201
    r = await add("me0@gmail.com")
    assert (r.status_code, r.json()["error"]["code"]) == (409, "already_added")
    r = await add("me3@gmail.com")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "too_many")
    missing = await client.delete("/api/v1/mail/senders/00000000-0000-0000-0000-000000000000", headers=h)
    assert missing.status_code == 404
