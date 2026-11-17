"""Cross-user isolation. These must never regress: one user can't see or touch another's data."""

import os

import asyncpg
import pytest

from tests import samples
from tests.conftest import VALID_PROFILE, auth, signup


@pytest.fixture
async def two_users(client):
    a = await signup(client, name="Alice")
    b = await signup(client, name="Bob")
    client.cookies.clear()
    return auth(a["access_token"]), auth(b["access_token"])


async def test_profiles_are_invisible_to_other_users(client, two_users):
    ha, hb = two_users
    pa = (await client.post("/api/v1/profiles", headers=ha, json=VALID_PROFILE)).json()

    assert (await client.get("/api/v1/profiles", headers=hb)).json() == []
    assert (await client.get(f"/api/v1/profiles/{pa['id']}", headers=hb)).status_code == 404
    r = await client.patch(f"/api/v1/profiles/{pa['id']}", headers=hb, json={"threshold": 50, "version": 1})
    assert r.status_code == 404
    assert (await client.delete(f"/api/v1/profiles/{pa['id']}", headers=hb)).status_code == 404

    # Same name is fine for a different user.
    assert (await client.post("/api/v1/profiles", headers=hb, json=VALID_PROFILE)).status_code == 201
    # Alice's profile is untouched.
    assert (await client.get(f"/api/v1/profiles/{pa['id']}", headers=ha)).json()["threshold"] == 85


async def test_candidate_profiles_are_separate(client, two_users):
    ha, hb = two_users
    await client.put("/api/v1/candidate", headers=ha, json={"summary": "Alice only", "version": 1})
    assert (await client.get("/api/v1/candidate", headers=hb)).json()["summary"] is None


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def test_rls_blocks_raw_queries_without_user_scope(client, two_users):
    """Even a hand-written query as the app role sees nothing unless app.user_id is set."""
    ha, _ = two_users
    await client.post("/api/v1/profiles", headers=ha, json=VALID_PROFILE)
    conn = await asyncpg.connect(_dsn(os.environ["DATABASE_URL"]))
    try:
        assert await conn.fetchval("select count(*) from search_profiles") == 0
        assert await conn.fetchval("select count(*) from candidate_profiles") == 0
        # A forged insert for someone else's user_id is rejected by WITH CHECK.
        users = await conn.fetch("select id from users order by created_at")
        async with conn.transaction():
            await conn.execute("select set_config('app.user_id', $1, true)", str(users[1]["id"]))
            with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
                await conn.execute(
                    "insert into search_profiles (user_id, name, target_roles, locations, work_models, "
                    "min_seniority, weights) values ($1, 'x', '{a}', '{b}', '{Remote}', 5, '{}')",
                    users[0]["id"],
                )
    finally:
        await conn.close()


async def _as_user(conn, user_id, sql: str, *args):
    async with conn.transaction():
        await conn.execute("select set_config('app.user_id', $1, true)", str(user_id))
        return await conn.fetchval(sql, *args)


async def test_ingestion_tables_are_private(client, two_users):
    """Received emails, raw bodies and each user's jobs: only the owner sees them. The catalog is shared."""
    conn = await asyncpg.connect(_dsn(os.environ["DATABASE_URL"]))
    try:
        alice, bob = [r["id"] for r in await conn.fetch("select id from users order by created_at")]
        msg = await _as_user(
            conn,
            alice,
            "insert into inbound_messages (user_id, message_id, sender) values ($1, '<m1@x>', 'a@linkedin.com') "
            "returning id",
            alice,
        )
        await _as_user(conn, alice, "insert into inbound_raw values ($1, $2, 'raw')", msg, alice)
        job = await conn.fetchval("insert into jobs (title, company) values ('CTO', 'Acme') returning id")
        await _as_user(
            conn,
            alice,
            "insert into user_jobs (user_id, job_id, lead, apply_url) values ($1, $2, 'alert', 'secret')",
            alice,
            job,
        )

        for table in ("inbound_messages", "inbound_raw", "user_jobs"):
            assert await _as_user(conn, alice, f"select count(*) from {table}") == 1
            assert await _as_user(conn, bob, f"select count(*) from {table}") == 0
            assert await conn.fetchval(f"select count(*) from {table}") == 0  # no user scope at all
        assert await _as_user(conn, bob, "select count(*) from jobs") == 1  # shared catalog

        # Bob can't plant rows on Alice's account.
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_user(
                conn,
                bob,
                "insert into user_jobs (user_id, job_id, lead) values ($1, $2, 'alert')",
                alice,
                job,
            )
    finally:
        await conn.close()


async def test_resume_tables_are_private(client, two_users):
    """Resumes, cover letters, stored files, job matches and the AI call log: only the owner sees them."""
    conn = await asyncpg.connect(_dsn(os.environ["DATABASE_URL"]))
    try:
        alice, bob = [r["id"] for r in await conn.fetch("select id from users order by created_at")]
        f = await _as_user(
            conn,
            alice,
            "insert into stored_files (id, user_id, name, kind, size, sha256, data) "
            "values (gen_random_uuid(), $1, 'cv.pdf', 'pdf', 3, 'x', 'abc') returning id",
            alice,
        )
        resume = await _as_user(
            conn,
            alice,
            "insert into resumes (id, user_id, label, text, file_id, is_primary) "
            "values (gen_random_uuid(), $1, 'CV', 'text', $2, true) returning id",
            alice,
            f,
        )
        await _as_user(
            conn,
            alice,
            "insert into cover_letters (id, user_id, label, text) values (gen_random_uuid(), $1, 'L', 't') returning id",
            alice,
        )
        job = await conn.fetchval("insert into jobs (title) values ('CTO') returning id")
        uj = await _as_user(
            conn,
            alice,
            "insert into user_jobs (user_id, job_id, lead) values ($1, $2, 'alert') returning id",
            alice,
            job,
        )
        await _as_user(
            conn,
            alice,
            "insert into job_matches (user_job_id, user_id, band, score, best_resume_id) "
            "values ($1, $2, 'strong', 90, $3) returning user_job_id",
            uj,
            alice,
            resume,
        )
        await _as_user(
            conn,
            alice,
            "insert into llm_calls (user_id, provider, model, prompt, ok) values ($1, 'voyage', 'm', 'p', true) "
            "returning id",
            alice,
        )

        for table in ("stored_files", "resumes", "cover_letters", "job_matches", "llm_calls"):
            assert await _as_user(conn, alice, f"select count(*) from {table}") == 1, table
            assert await _as_user(conn, bob, f"select count(*) from {table}") == 0, table
            assert await conn.fetchval(f"select count(*) from {table}") == 0, table

        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_user(
                conn,
                bob,
                "insert into resumes (id, user_id, label, text) values (gen_random_uuid(), $1, 'x', 'y')",
                alice,
            )
    finally:
        await conn.close()


async def test_resumes_and_matches_are_invisible_through_the_api(client, two_users):
    from tests import samples

    ha, hb = two_users
    resume = (await client.post("/api/v1/resumes", headers=ha, json={"text": samples.RESUME})).json()
    letter = (
        await client.post("/api/v1/cover-letters", headers=ha, json={"text": samples.COVER_LETTER})
    ).json()

    assert (await client.get("/api/v1/resumes", headers=hb)).json()["items"] == []
    assert (await client.get("/api/v1/cover-letters", headers=hb)).json()["items"] == []
    for path in (
        f"/api/v1/resumes/{resume['id']}",
        f"/api/v1/resumes/{resume['id']}/file",
        f"/api/v1/cover-letters/{letter['id']}",
    ):
        assert (await client.get(path, headers=hb)).status_code == 404, path
    assert (await client.post(f"/api/v1/resumes/{resume['id']}/primary", headers=hb)).status_code == 404
    assert (await client.delete(f"/api/v1/cover-letters/{letter['id']}", headers=hb)).status_code == 404
    r = await client.post("/api/v1/candidate/from-resume", headers=hb, json={"resume_id": resume["id"]})
    assert r.status_code == 404
    # Bob's own status counts nothing of Alice's.
    assert (await client.get("/api/v1/matching/status", headers=hb)).json()["resumes"] == 0


async def test_app_role_cannot_delete_from_the_shared_catalog(client):
    conn = await asyncpg.connect(_dsn(os.environ["DATABASE_URL"]))
    try:
        job = await conn.fetchval("insert into jobs (title) values ('CTO') returning id")
        await conn.execute(
            "insert into job_sources (job_id, source, source_job_id) values ($1, 'linkedin', '1')", job
        )
        for table in ("job_sources", "jobs"):
            with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
                await conn.execute(f"delete from {table}")
    finally:
        await conn.close()


async def test_app_role_can_queue_background_jobs(client):
    """The worker and the API connect as the app role; Procrastinate's tables must be usable by it."""
    from app.core.worker import defer

    job_id = await defer("tests.noop", x=1)
    conn = await asyncpg.connect(_dsn(os.environ["DATABASE_URL"]))
    try:
        row = await conn.fetchrow("select task_name, status from procrastinate_jobs where id = $1", job_id)
        assert (row["task_name"], row["status"]) == ("tests.noop", "todo")
    finally:
        await conn.close()


async def test_app_role_cannot_bypass_rls(client):
    conn = await asyncpg.connect(_dsn(os.environ["DATABASE_URL"]))
    try:
        row = await conn.fetchrow("select rolsuper, rolbypassrls from pg_roles where rolname = current_user")
        assert row["rolsuper"] is False and row["rolbypassrls"] is False
    finally:
        await conn.close()


async def test_answer_bank_is_private(client, two_users):
    conn = await asyncpg.connect(_dsn(os.environ["DATABASE_URL"]))
    try:
        alice, bob = [r["id"] for r in await conn.fetch("select id from users order by created_at")]
        await _as_user(
            conn,
            alice,
            "insert into answers (id, user_id, key, question, answer) "
            "values (gen_random_uuid(), $1, 'notice_period', 'Notice?', '90 days') returning id",
            alice,
        )
        assert await _as_user(conn, alice, "select count(*) from answers") == 1
        assert await _as_user(conn, bob, "select count(*) from answers") == 0
        assert await conn.fetchval("select count(*) from answers") == 0
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_user(
                conn,
                bob,
                "insert into answers (id, user_id, key, question, answer) values (gen_random_uuid(), $1, 'x_y', 'q', 'a')",
                alice,
            )
    finally:
        await conn.close()


async def test_applications_and_contacts_are_private(client, two_users):
    """Milestone 5 tables: applications, their timeline and contacts on a job."""
    conn = await asyncpg.connect(_dsn(os.environ["DATABASE_URL"]))
    try:
        alice, bob = [r["id"] for r in await conn.fetch("select id from users order by created_at")]
        job_id = await conn.fetchval(
            "insert into jobs (id, fingerprint, title) values (gen_random_uuid(), 'fp-m5', 'VP') returning id"
        )
        uj = await _as_user(
            conn,
            alice,
            "insert into user_jobs (id, user_id, job_id, lead) values (gen_random_uuid(), $1, $2, 'alert') "
            "returning id",
            alice,
            job_id,
        )
        app = await _as_user(
            conn,
            alice,
            "insert into applications (id, user_id, user_job_id, applied_on) "
            "values (gen_random_uuid(), $1, $2, current_date) returning id",
            alice,
            uj,
        )
        await _as_user(
            conn,
            alice,
            "insert into application_events (id, user_id, application_id, kind) "
            "values (gen_random_uuid(), $1, $2, 'applied') returning id",
            alice,
            app,
        )
        await _as_user(
            conn,
            alice,
            "insert into job_contacts (id, user_id, user_job_id, name) "
            "values (gen_random_uuid(), $1, $2, 'Priya') returning id",
            alice,
            uj,
        )
        for t in ("applications", "application_events", "job_contacts"):
            assert await _as_user(conn, alice, f"select count(*) from {t}") == 1, t
            assert await _as_user(conn, bob, f"select count(*) from {t}") == 0, t
            assert await conn.fetchval(f"select count(*) from {t}") == 0, t
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_user(
                conn,
                bob,
                "insert into job_contacts (id, user_id, user_job_id, name) "
                "values (gen_random_uuid(), $1, $2, 'x') returning id",
                alice,
                uj,
            )
    finally:
        await conn.close()


async def test_app_role_can_change_but_not_add_or_remove_app_settings(client):
    conn = await asyncpg.connect(_dsn(os.environ["DATABASE_URL"]))
    try:
        assert await conn.fetchval("select count(*) from app_settings") == 2
        await conn.execute("update app_settings set value = '31' where key = 'job_expiry_warn_days'")
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.execute("insert into app_settings (key, value) values ('x', '1')")
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await conn.execute("delete from app_settings")
    finally:
        await conn.close()


async def test_source_runs_are_private(client, two_users):
    """What each Google Alerts read found is private to the user."""
    conn = await asyncpg.connect(_dsn(os.environ["DATABASE_URL"]))
    try:
        alice, bob = [r["id"] for r in await conn.fetch("select id from users order by created_at")]
        await _as_user(
            conn,
            alice,
            "insert into source_runs (user_id, source, found) values ($1, 'google_alert', 3) returning id",
            alice,
        )
        assert await _as_user(conn, alice, "select count(*) from source_runs") == 1
        assert await _as_user(conn, bob, "select count(*) from source_runs") == 0
        assert await conn.fetchval("select count(*) from source_runs") == 0
    finally:
        await conn.close()


async def test_forwarding_addresses_are_private(client, two_users):
    """The addresses a user forwards alerts from by hand: only the owner sees or changes them."""
    ha, hb = two_users
    r = await client.post("/api/v1/mail/senders", headers=ha, json={"address": "alice@gmail.com"})
    assert r.status_code == 201
    assert (await client.get("/api/v1/mail", headers=hb)).json()["forward_senders"] == []
    assert (await client.delete(f"/api/v1/mail/senders/{r.json()['id']}", headers=hb)).status_code == 404

    conn = await asyncpg.connect(_dsn(os.environ["DATABASE_URL"]))
    try:
        alice, bob = [r["id"] for r in await conn.fetch("select id from users order by created_at")]
        assert await _as_user(conn, alice, "select count(*) from forward_senders") == 1
        assert await _as_user(conn, bob, "select count(*) from forward_senders") == 0
        assert await conn.fetchval("select count(*) from forward_senders") == 0
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_user(
                conn,
                bob,
                "insert into forward_senders (user_id, address) values ($1, 'bob@gmail.com') returning id",
                alice,
            )
    finally:
        await conn.close()


async def test_whatsapp_numbers_and_messages_are_private(client, two_users):
    """A user's WhatsApp number and the messages sent to it: only the owner sees them."""
    ha, hb = two_users
    r = await client.post("/api/v1/notifications/whatsapp/number", headers=ha, json={"number": "9876543210"})
    assert r.status_code == 200 and r.json()["recent"]
    bob_view = (await client.get("/api/v1/notifications/whatsapp", headers=hb)).json()
    assert bob_view["number"] is None and bob_view["recent"] == []

    conn = await asyncpg.connect(_dsn(os.environ["DATABASE_URL"]))
    try:
        alice, bob = [r["id"] for r in await conn.fetch("select id from users order by created_at")]
        assert await _as_user(conn, alice, "select count(*) from notifications") == 1
        assert await _as_user(conn, bob, "select count(*) from notifications") == 0
        assert await conn.fetchval("select count(*) from notifications") == 0
        number = "select whatsapp_number from notification_settings where user_id = $1"
        assert await _as_user(conn, bob, number, alice) is None
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_user(
                conn,
                bob,
                "insert into notifications (user_id, kind, body) values ($1, 'test', 'hi') returning id",
                alice,
            )
    finally:
        await conn.close()


async def test_duplicate_pairs_are_private(client, two_users):
    """Milestone 9.3: which of a user's jobs are the same role, and their answers, are private."""
    conn = await asyncpg.connect(_dsn(os.environ["DATABASE_URL"]))
    try:
        alice, bob = [r["id"] for r in await conn.fetch("select id from users order by created_at")]
        job = await conn.fetchval("insert into jobs (title) values ('VP Engineering') returning id")
        other = await conn.fetchval(
            "insert into jobs (title) values ('Vice President, Engineering') returning id"
        )
        new_row = "insert into user_jobs (user_id, job_id, lead) values ($1, $2, 'alert') returning id"
        one = await _as_user(conn, alice, new_row, alice, job)
        two = await _as_user(conn, alice, new_row, alice, other)
        pair = (
            "insert into job_duplicates (user_id, user_job_id, other_id, kind, reason) "
            "values ($1, $2, $3, 'likely', 'test') returning id"
        )
        await _as_user(conn, alice, pair, alice, two, one)
        assert await _as_user(conn, alice, "select count(*) from job_duplicates") == 1
        assert await _as_user(conn, bob, "select count(*) from job_duplicates") == 0
        assert await conn.fetchval("select count(*) from job_duplicates") == 0
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_user(conn, bob, pair, alice, two, one)
    finally:
        await conn.close()


async def test_feedback_and_learned_preferences_are_private(client, two_users):
    """Milestone 13 A: "Not for me" reasons and what they taught are private."""
    conn = await asyncpg.connect(_dsn(os.environ["DATABASE_URL"]))
    try:
        alice, bob = [r["id"] for r in await conn.fetch("select id from users order by created_at")]
        job = await conn.fetchval("insert into jobs (title) values ('VP Engineering') returning id")
        new_row = "insert into user_jobs (user_id, job_id, lead) values ($1, $2, 'alert') returning id"
        uj = await _as_user(conn, alice, new_row, alice, job)
        fb = "insert into job_feedback (user_id, user_job_id, reason) values ($1, $2, 'company') returning id"
        await _as_user(conn, alice, fb, alice, uj)
        pref = (
            "insert into learned_preferences (user_id, kind, value, label) "
            "values ($1, 'company', 'Okta', 'Jobs at Okta') returning id"
        )
        await _as_user(conn, alice, pref, alice)
        for table in ("job_feedback", "learned_preferences"):
            assert await _as_user(conn, alice, f"select count(*) from {table}") == 1
            assert await _as_user(conn, bob, f"select count(*) from {table}") == 0
            assert await conn.fetchval(f"select count(*) from {table}") == 0
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await _as_user(conn, bob, pref, alice)
    finally:
        await conn.close()


async def test_match_profiles_are_invisible_to_other_users(client, two_users):
    ha, hb = two_users
    await client.post("/api/v1/resumes", json={"text": samples.RESUME, "label": "Cloud and AI"}, headers=ha)
    pa = next(p for p in (await client.get("/api/v1/profiles", headers=ha)).json() if p["resume_id"])
    assert (await client.get("/api/v1/profiles", headers=hb)).json() == []
    assert (await client.post(f"/api/v1/profiles/{pa['id']}/refresh", headers=hb)).status_code == 404
    r = await client.post(f"/api/v1/profiles/{pa['id']}/skills", headers=hb, json={"skill": "Go"})
    assert r.status_code == 404
    assert (await client.get(f"/api/v1/profiles/{pa['id']}", headers=ha)).json()["skills"] == []


async def test_google_alert_feeds_are_private(client, two_users):
    """A Google Alerts feed link is personal: only the owner sees or removes it."""
    ha, hb = two_users
    url = "https://www.google.com/alerts/feeds/01234567890123456789/11111111111111111111"
    r = await client.post("/api/v1/alerts", headers=ha, json={"feed_url": url})
    assert r.status_code == 201
    assert (await client.get("/api/v1/alerts", headers=hb)).json()["feeds"] == []
    assert (await client.delete(f"/api/v1/alerts/{r.json()['id']}", headers=hb)).status_code == 404
    # Bob may add the same feed link as his own row; Alice's stays hers.
    assert (await client.post("/api/v1/alerts", headers=hb, json={"feed_url": url})).status_code == 201
    assert len((await client.get("/api/v1/alerts", headers=ha)).json()["feeds"]) == 1


async def test_subscriptions_are_private(client, super_admin):
    """Plans and coupons (2026-11-17): each period is the job seeker's own."""
    from tests.test_access import invite, new_seeker, token_of

    a = await new_seeker(client)
    await new_seeker(client)
    made = await invite(client, super_admin, a["user"]["email"], months=1)
    await client.post("/api/v1/invites/accept", headers=a["headers"], json={"token": token_of(made)})
    conn = await asyncpg.connect(os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    try:
        assert await conn.fetchval("select count(*) from subscriptions") == 0  # no user scope: nothing
        ids = [
            r["id"]
            for r in await conn.fetch("select id from users where email like 'seeker-%' order by created_at")
        ]
        async with conn.transaction():
            await conn.execute("select set_config('app.user_id', $1, true)", str(ids[1]))
            assert await conn.fetchval("select count(*) from subscriptions") == 0  # the other user's
        async with conn.transaction():
            await conn.execute("select set_config('app.user_id', $1, true)", str(ids[0]))
            assert await conn.fetchval("select count(*) from subscriptions") == 1
    finally:
        await conn.close()
