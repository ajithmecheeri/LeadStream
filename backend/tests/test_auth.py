import re

from app.core.config import get_settings
from tests.conftest import PASSWORD, auth, signup, unique_email


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.headers["x-request-id"]


async def test_signup_returns_token_cookie_and_forwarding_address(client):
    email = unique_email()
    data = await signup(client, email=email)
    assert data["access_token"]
    assert data["refresh_token"] is None  # web clients get the cookie instead
    assert data["user"]["email"] == email
    domain = re.escape(get_settings().inbound_domain)
    assert re.fullmatch(rf"alerts-[a-z2-9]{{10}}@{domain}", data["user"]["forwarding_address"])
    assert "ff_refresh" in client.cookies


async def test_signup_creates_empty_candidate_profile_and_settings(client, user):
    r = await client.get("/api/v1/candidate", headers=user["headers"])
    assert r.status_code == 200
    assert r.json()["version"] == 1 and r.json()["skills"] == []
    r = await client.get("/api/v1/settings/notifications", headers=user["headers"])
    assert r.status_code == 200 and r.json()["max_push_per_day"] == 10


async def test_signup_duplicate_email_is_case_insensitive(client):
    email = unique_email()
    await signup(client, email=email)
    r = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": email.upper(),
            "first_name": "X",
            "last_name": "Y",
            "password": PASSWORD,
            "password_confirm": PASSWORD,
            "accept_terms": True,
            "job_locations": ["Bengaluru"],
        },
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"


async def test_signup_validation_envelope(client):
    r = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": "not-an-email",
            "first_name": " ",
            "last_name": "",
            "password": "short",
            "accept_terms": False,
        },
    )
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    fields = {d["field"] for d in err["details"]}
    assert {"email", "first_name", "last_name", "password", "password_confirm", "accept_terms"} <= fields
    assert err["request_id"]


async def test_signup_needs_the_same_password_twice(client):
    body = {
        "email": unique_email(),
        "first_name": "X",
        "last_name": "Y",
        "password": PASSWORD,
        "accept_terms": True,
        "job_locations": ["Bengaluru"],
    }
    r = await client.post("/api/v1/auth/signup", json={**body, "password_confirm": PASSWORD + "x"})
    assert r.status_code == 422
    (detail,) = r.json()["error"]["details"]
    assert detail["field"] == "password_confirm" and "don't match" in detail["message"]
    r = await client.post("/api/v1/auth/signup", json={**body, "password_confirm": PASSWORD})
    assert r.status_code == 201


async def test_login_success_and_wrong_password(client):
    email = unique_email()
    await signup(client, email=email)
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "bad_credentials"
    r = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever-123"}
    )
    assert r.status_code == 401 and r.json()["error"]["code"] == "bad_credentials"
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200
    me = await client.get("/api/v1/me", headers=auth(r.json()["access_token"]))
    assert me.json()["email"] == email


async def test_me_requires_valid_token(client):
    assert (await client.get("/api/v1/me")).json()["error"]["code"] == "unauthorized"
    r = await client.get("/api/v1/me", headers=auth("garbage"))
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"


async def test_patch_me(client, user):
    r = await client.patch(
        "/api/v1/me",
        headers=user["headers"],
        json={"first_name": "  New ", "last_name": "Name", "timezone": "Asia/Dubai"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "New Name" and r.json()["timezone"] == "Asia/Dubai"
    r = await client.patch("/api/v1/me", headers=user["headers"], json={"timezone": "Mars/Base"})
    assert r.status_code == 422


async def test_refresh_rotates_cookie(client):
    await signup(client)
    old = client.cookies["ff_refresh"]
    r = await client.post("/api/v1/auth/refresh")
    assert r.status_code == 200 and r.json()["access_token"]
    assert client.cookies["ff_refresh"] != old


async def test_refresh_reuse_revokes_family(client):
    await signup(client)
    first = client.cookies["ff_refresh"]
    r = await client.post("/api/v1/auth/refresh")
    assert r.status_code == 200
    second = client.cookies["ff_refresh"]
    client.cookies.clear()
    # Replaying the rotated token is treated as theft...
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert r.status_code == 401 and r.json()["error"]["code"] == "refresh_reused"
    # ...and the legitimate newer token is revoked too.
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": second})
    assert r.status_code == 401 and r.json()["error"]["code"] == "refresh_invalid"


async def test_mobile_client_gets_refresh_token_in_body(client):
    email = unique_email()
    await signup(client, email=email)
    client.cookies.clear()
    r = await client.post(
        "/api/v1/auth/login", headers={"X-Client": "mobile"}, json={"email": email, "password": PASSWORD}
    )
    body = r.json()
    assert body["refresh_token"] and "ff_refresh" not in client.cookies
    r = await client.post(
        "/api/v1/auth/refresh", headers={"X-Client": "mobile"}, json={"refresh_token": body["refresh_token"]}
    )
    assert r.status_code == 200 and r.json()["refresh_token"] != body["refresh_token"]


async def test_logout_revokes_refresh(client):
    await signup(client)
    token = client.cookies["ff_refresh"]
    r = await client.post("/api/v1/auth/logout")
    assert r.status_code == 204
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert r.status_code == 401


async def test_login_is_throttled_after_repeated_failures(client):
    email = unique_email()
    await signup(client, email=email)
    for _ in range(10):
        r = await client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
        assert r.status_code == 401
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_attempts"


async def test_signup_with_first_middle_and_last_name(client):
    body = {
        "email": unique_email(),
        "first_name": " Ajith ",
        "middle_name": "  Kumar ",
        "last_name": "Mecheri",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
        "accept_terms": True,
        "job_locations": ["Bengaluru"],
    }
    me = (await client.post("/api/v1/auth/signup", json=body)).json()["user"]
    assert (me["first_name"], me["middle_name"], me["last_name"], me["name"]) == (
        "Ajith",
        "Kumar",
        "Mecheri",
        "Ajith Kumar Mecheri",
    )
    no_middle = (
        await client.post("/api/v1/auth/signup", json={**body, "email": unique_email(), "middle_name": " "})
    ).json()
    assert (no_middle["user"]["middle_name"], no_middle["user"]["name"]) == (None, "Ajith Mecheri")


async def test_change_or_clear_name_parts(client, user):
    h = user["headers"]
    r = await client.patch("/api/v1/me", headers=h, json={"middle_name": "Kumar"})
    assert r.json()["name"] == "Test Kumar User"
    r = await client.patch("/api/v1/me", headers=h, json={"middle_name": None})
    assert (r.json()["middle_name"], r.json()["name"]) == (None, "Test User")
    r = await client.patch("/api/v1/me", headers=h, json={"first_name": "  "})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "first_name"
