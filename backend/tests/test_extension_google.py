"""POC (user, 2026-11-17): the extension's "Add to BrewMyJob" button on Google's results (app/modules/extension/google.py).
Delete this file with the POC."""

from tests.test_extension import paired

LINKEDIN = "https://in.linkedin.com/jobs/view/head-of-engineering-at-acme-group-4490581539"


async def test_a_google_result_becomes_a_job_in_the_list(client, account):
    ext = await paired(client, account)
    body = {
        # Google's redirect, as the result's link can be
        "url": "https://www.google.com/url?q=" + LINKEDIN + "&sa=U",
        "title": "Acme Group hiring Head of Engineering in Bengaluru, Karnataka, India | LinkedIn",
        "snippet": "Lead a team of 40 engineers building payments.",
    }
    r = await client.post("/api/v1/extension/google-result", json=body, headers=ext["headers"])
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["title"], out["company"], out["already"]) == ("Head of Engineering", "Acme Group", False)

    job = (await client.get(f"/api/v1/jobs/{out['user_job_id']}", headers=account["headers"])).json()
    assert (job["job"]["title"], job["job"]["company"]) == ("Head of Engineering", "Acme Group")

    # It waits in Jobs → From Google, not in Top or Other, until the user keeps it.
    h = account["headers"]
    assert job["status"] == "review"
    assert (await client.get("/api/v1/jobs/stats", headers=h)).json()["review"] == 1
    listed = (await client.get("/api/v1/jobs", params={"status": "review"}, headers=h)).json()
    assert [j["id"] for j in listed["items"]] == [out["user_job_id"]]
    active = (await client.get("/api/v1/jobs", headers=h)).json()
    assert out["user_job_id"] not in [j["id"] for j in active["items"]]
    r = await client.patch(
        f"/api/v1/jobs/{out['user_job_id']}", json={"status": "seen", "version": job["version"]}, headers=h
    )
    assert r.status_code == 200, r.text
    assert (await client.get("/api/v1/jobs/stats", headers=h)).json()["review"] == 0
    # A job can't be sent back to review.
    r = await client.patch(
        f"/api/v1/jobs/{out['user_job_id']}",
        json={"status": "review", "version": r.json()["version"]},
        headers=h,
    )
    assert r.status_code == 422

    # Clicking again doesn't add it twice.
    r = await client.post("/api/v1/extension/google-result", json=body, headers=ext["headers"])
    assert r.status_code == 201
    assert (r.json()["user_job_id"], r.json()["already"]) == (out["user_job_id"], True)


async def test_only_portal_job_pages_with_an_extension_token(client, account):
    body = {"url": "https://example.com/careers/123", "title": "Engineer at Example"}
    assert (await client.post("/api/v1/extension/google-result", json=body)).status_code == 401
    r = await client.post("/api/v1/extension/google-result", json=body, headers=account["headers"])
    assert r.status_code == 401  # a user's access token isn't an extension token
    ext = await paired(client, account)
    r = await client.post("/api/v1/extension/google-result", json=body, headers=ext["headers"])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "not_a_job_link"
