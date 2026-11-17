"""Roles, plans, coupons and invites (user, 2026-11-17; docs/plan-roles-and-plans.md)."""

import uuid
from datetime import UTC, datetime

from app.modules.access.service import add_months
from tests.conftest import PASSWORD, admin_account, auth, signup


def seeker_email() -> str:
    """An address the tests' free-access pattern doesn't cover: this account needs a plan."""
    return f"seeker-{uuid.uuid4().hex[:8]}@example.org"


async def new_seeker(client, email: str | None = None) -> dict:
    data = await signup(client, email or seeker_email())
    client.cookies.clear()
    return {**data, "headers": auth(data["access_token"])}


async def invite(client, super_admin, email: str, role="job_seeker", months=0) -> dict:
    r = await client.post(
        "/api/v1/admin/invites",
        headers=super_admin["headers"],
        json={"email": email, "role": role, "free_months": months},
    )
    assert r.status_code == 201, r.text
    return r.json()


def token_of(made: dict) -> str:
    return made["link"].split("token=")[1]


async def test_without_a_plan_a_job_seeker_sees_the_plans_only(client):
    s = await new_seeker(client)
    assert s["user"]["role"] == "job_seeker"
    assert s["user"]["access"] == {"active": False, "until": None, "why": "none"}
    r = await client.get("/api/v1/jobs", headers=s["headers"])
    assert r.status_code == 402 and r.json()["error"]["code"] == "subscription_required"
    plans = (await client.get("/api/v1/plans", headers=s["headers"])).json()
    assert [(p["months"], p["price_inr"]) for p in plans["plans"]] == [
        (1, 199),
        (3, 500),
        (6, 750),
        (12, 1200),
    ]
    assert plans["payments_open"] is False
    # The account itself stays reachable.
    assert (await client.get("/api/v1/me", headers=s["headers"])).status_code == 200


async def test_an_invite_with_a_coupon_gives_free_months_at_sign_up(client, super_admin):
    email = seeker_email()
    made = await invite(client, super_admin, email, months=3)
    assert made["state"] == "open" and "/invite?token=" in made["link"]
    view = (await client.get("/api/v1/invites/view", params={"token": token_of(made)})).json()
    assert view == {"email": email, "role": "job_seeker", "free_months": 3, "has_account": False}

    body = {
        "email": seeker_email(),  # someone else's address: refused
        "first_name": "Asha",
        "last_name": "Rao",
        "password": PASSWORD,
        "password_confirm": PASSWORD,
        "accept_terms": True,
        "job_locations": ["Bengaluru"],
        "invite": token_of(made),
    }
    r = await client.post("/api/v1/auth/signup", json=body)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "email"
    r = await client.post("/api/v1/auth/signup", json={**body, "email": email})
    assert r.status_code == 201, r.text
    access = r.json()["user"]["access"]
    assert access["active"] is True and access["why"] == "plan"
    until = datetime.fromisoformat(access["until"])
    assert abs((until - add_months(datetime.now(UTC), 3)).total_seconds()) < 120
    client.cookies.clear()
    assert (await client.get("/api/v1/jobs", headers=auth(r.json()["access_token"]))).status_code == 200

    # The link works once.
    r = await client.get("/api/v1/invites/view", params={"token": token_of(made)})
    assert r.status_code == 410 and r.json()["error"]["code"] == "invite_accepted"
    (row,) = (await client.get("/api/v1/admin/invites", headers=super_admin["headers"])).json()
    assert row["state"] == "accepted"


async def test_an_existing_account_accepts_and_coupons_add_up(client, super_admin):
    s = await new_seeker(client)
    email = s["user"]["email"]
    first = await invite(client, super_admin, email, months=1)
    assert (await client.get("/api/v1/invites/view", params={"token": token_of(first)})).json()["has_account"]
    r = await client.post("/api/v1/invites/accept", headers=s["headers"], json={"token": token_of(first)})
    assert r.status_code == 200 and r.json()["active"] is True
    one = datetime.fromisoformat(r.json()["until"])
    second = await invite(client, super_admin, email, months=3)
    r = await client.post("/api/v1/invites/accept", headers=s["headers"], json={"token": token_of(second)})
    assert datetime.fromisoformat(r.json()["until"]) == add_months(one, 3)  # starts when the first ends

    # Someone else can't use an invite made for this email.
    other = await new_seeker(client)
    third = await invite(client, super_admin, email, months=1)
    r = await client.post("/api/v1/invites/accept", headers=other["headers"], json={"token": token_of(third)})
    assert r.status_code == 403 and r.json()["error"]["code"] == "invite_other_email"

    # A new session carries the period: the app opens.
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    client.cookies.clear()
    assert (await client.get("/api/v1/jobs", headers=auth(r.json()["access_token"]))).status_code == 200


async def test_an_admin_invite_makes_an_admin_who_needs_no_plan(client, super_admin):
    s = await new_seeker(client)
    assert (await client.get("/api/v1/jobs", headers=s["headers"])).status_code == 402
    made = await invite(client, super_admin, s["user"]["email"], role="admin", months=3)
    assert made["free_months"] == 0  # admins never need a plan
    r = await client.post("/api/v1/invites/accept", headers=s["headers"], json={"token": token_of(made)})
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/login", json={"email": s["user"]["email"], "password": PASSWORD})
    client.cookies.clear()
    assert r.json()["user"]["role"] == "admin" and r.json()["user"]["access"]["why"] == "admin"
    admin = auth(r.json()["access_token"])
    assert (await client.get("/api/v1/jobs", headers=admin)).status_code == 200
    # Invites and Admin settings stay with the super admin.
    assert (await client.get("/api/v1/admin/invites", headers=admin)).status_code == 403
    assert (await client.get("/api/v1/admin/settings", headers=admin)).status_code == 403


async def test_job_seekers_cant_manage_invites(client, user):
    """`user` is a test account with free access: a job seeker."""
    assert (
        await client.post("/api/v1/admin/invites", headers=user["headers"], json={"email": "a@b.co"})
    ).status_code == 403


async def test_invites_can_be_revoked_and_coupons_are_1_or_3_months(client, super_admin):
    made = await invite(client, super_admin, seeker_email(), months=1)
    r = await client.delete(f"/api/v1/admin/invites/{made['id']}", headers=super_admin["headers"])
    assert r.status_code == 204
    r = await client.get("/api/v1/invites/view", params={"token": token_of(made)})
    assert r.status_code == 410 and r.json()["error"]["code"] == "invite_revoked"
    assert (
        await client.delete(f"/api/v1/admin/invites/{made['id']}", headers=super_admin["headers"])
    ).status_code == 404
    r = await client.post(
        "/api/v1/admin/invites",
        headers=super_admin["headers"],
        json={"email": "x@example.org", "free_months": 6},
    )
    assert r.status_code == 422
    assert (
        await client.get("/api/v1/invites/view", params={"token": "bmjinv_nonsense-token"})
    ).status_code == 404


async def test_a_super_admin_needs_no_plan(client):
    sa = await admin_account(client, "super_admin")
    me = (await client.get("/api/v1/me", headers=sa["headers"])).json()
    assert me["access"] == {"active": True, "until": None, "why": "admin"}
    assert (await client.get("/api/v1/admin/invites", headers=sa["headers"])).status_code == 200
