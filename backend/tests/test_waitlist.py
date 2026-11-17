"""The home page waitlist: anyone can join, the answer never reveals who is on it, only the super admin lists it."""

from app.admin import set_role
from tests.conftest import PASSWORD, auth


async def _admin_headers(client, email: str) -> dict:
    assert "now the super admin" in await set_role(email, "super_admin")
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    client.cookies.clear()
    return auth(r.json()["access_token"])


async def test_join_once_whatever_the_case(client, user):
    for email in ("Asha@Example.com", "asha@example.com", "ravi@example.com"):
        r = await client.post("/api/v1/waitlist", json={"email": email})
        assert r.status_code == 201 and r.json() == {"joined": True}

    admin = await _admin_headers(client, user["user"]["email"])
    body = (await client.get("/api/v1/admin/waitlist", headers=admin)).json()
    assert body["total"] == 2
    # The first spelling is kept (email validation lower-cases the domain).
    assert [e["email"] for e in body["entries"]] == ["ravi@example.com", "Asha@example.com"]
    assert body["entries"][0]["source"] == "home"


async def test_bots_filling_the_hidden_field_are_not_added(client, user):
    r = await client.post("/api/v1/waitlist", json={"email": "bot@example.com", "website": "http://spam"})
    assert r.status_code == 201
    admin = await _admin_headers(client, user["user"]["email"])
    assert (await client.get("/api/v1/admin/waitlist", headers=admin)).json()["total"] == 0


async def test_bad_email_or_source(client):
    for body in ({"email": "not-an-email"}, {"email": "a@example.com", "source": "elsewhere"}, {}):
        r = await client.post("/api/v1/waitlist", json=body)
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_error"


async def test_only_the_super_admin_lists_it(client, user):
    assert (await client.get("/api/v1/admin/waitlist")).status_code == 401
    r = await client.get("/api/v1/admin/waitlist", headers=user["headers"])
    assert r.status_code == 403


async def test_a_contact_message_reaches_only_the_super_admin(client, user):
    msg = {
        "name": "Asha",
        "email": "asha@example.com",
        "topic": "privacy",
        "message": "Please delete my data.",
    }
    r = await client.post("/api/v1/contact", json=msg)
    assert r.status_code == 201 and r.json() == {"received": True}
    bot = {**msg, "website": "http://spam"}
    assert (await client.post("/api/v1/contact", json=bot)).status_code == 201  # same answer, not kept

    assert (await client.get("/api/v1/admin/contact", headers=user["headers"])).status_code == 403
    admin = await _admin_headers(client, user["user"]["email"])
    body = (await client.get("/api/v1/admin/contact", headers=admin)).json()
    assert body["total"] == 1
    assert body["messages"][0] | {"created_at": None} == {**msg, "created_at": None}


async def test_a_contact_message_needs_a_name_an_email_and_some_words(client):
    r = await client.post("/api/v1/contact", json={"name": "", "email": "x", "message": "hi"})
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"name", "email", "message"} <= fields
    r = await client.post(
        "/api/v1/contact", json={"name": "A", "email": "a@example.com", "topic": "sales", "message": "x" * 20}
    )
    assert r.status_code == 422
