from tests.conftest import VALID_PROFILE


async def test_meta(client, user):
    r = await client.get("/api/v1/profiles/meta", headers=user["headers"])
    body = r.json()
    assert sum(body["default_weights"].values()) == 100
    assert set(body["factors"]) == set(body["default_weights"])


async def test_create_list_get_patch_delete(client, user):
    h = user["headers"]
    r = await client.post(
        "/api/v1/profiles",
        headers=h,
        json={
            **VALID_PROFILE,
            "target_roles": ["VP Engineering", " vp engineering ", "Head of  Engineering"],
        },
    )
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["target_roles"] == ["VP Engineering", "Head of Engineering"]  # trimmed and de-duplicated
    assert sum(p["weights"].values()) == 100 and p["threshold"] == 85 and p["version"] == 1

    assert [x["id"] for x in (await client.get("/api/v1/profiles", headers=h)).json()] == [p["id"]]

    r = await client.patch(f"/api/v1/profiles/{p['id']}", headers=h, json={"threshold": 80, "version": 1})
    assert r.status_code == 200 and r.json()["threshold"] == 80 and r.json()["version"] == 2

    r = await client.patch(f"/api/v1/profiles/{p['id']}", headers=h, json={"threshold": 90, "version": 1})
    assert r.status_code == 409 and r.json()["error"]["code"] == "version_conflict"

    assert (await client.delete(f"/api/v1/profiles/{p['id']}", headers=h)).status_code == 204
    assert (await client.get(f"/api/v1/profiles/{p['id']}", headers=h)).status_code == 404


async def test_weights_must_sum_to_100_and_use_known_factors(client, user):
    h = user["headers"]
    bad = {
        **VALID_PROFILE,
        "weights": {
            "role": 50,
            "exp": 50,
            "core": 10,
            "cloud": 0,
            "ai": 0,
            "domain": 0,
            "loc": 0,
            "skills": 0,
            "comp": 0,
        },
    }
    r = await client.post("/api/v1/profiles", headers=h, json=bad)
    assert r.status_code == 422 and "add up to 100" in r.text
    r = await client.post("/api/v1/profiles", headers=h, json={**VALID_PROFILE, "weights": {"role": 100}})
    assert r.status_code == 422 and "missing" in r.text


async def test_rejects_bad_work_model_and_seniority(client, user):
    r = await client.post(
        "/api/v1/profiles",
        headers=user["headers"],
        json={**VALID_PROFILE, "work_models": ["Moon"], "min_seniority": 12},
    )
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert r.status_code == 422 and {"work_models.0", "min_seniority"} <= fields


async def test_duplicate_name_and_limit(client, user):
    h = user["headers"]
    assert (await client.post("/api/v1/profiles", headers=h, json=VALID_PROFILE)).status_code == 201
    r = await client.post("/api/v1/profiles", headers=h, json={**VALID_PROFILE, "name": "vp engineering"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "name_taken"
    for i in range(4):
        assert (
            await client.post("/api/v1/profiles", headers=h, json={**VALID_PROFILE, "name": f"P{i}"})
        ).status_code == 201
    r = await client.post("/api/v1/profiles", headers=h, json={**VALID_PROFILE, "name": "One too many"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "limit_reached"


async def test_candidate_update_normalises_and_versions(client, user):
    h = user["headers"]
    r = await client.put(
        "/api/v1/candidate",
        headers=h,
        json={
            "summary": "Leader",
            "years_experience": 22,
            "skills": ["AWS", "aws ", "Kubernetes", "LLM", "Python", "Java"],
            "domains": ["FinTech"],
            "notice_days": 90,
            "expected_ctc": "1.2 Cr",
            "current_location": "Bengaluru",
            "version": 1,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["skills"] == ["aws", "kubernetes", "llm", "python", "java"]
    assert body["version"] == 2 and body["completeness"] == 86  # all but a resume (2026-11-13)
    r = await client.put("/api/v1/candidate", headers=h, json={"version": 1})
    assert r.status_code == 409


async def test_candidate_rejects_non_linkedin_url(client, user):
    r = await client.put(
        "/api/v1/candidate",
        headers=user["headers"],
        json={"linkedin_url": "https://evil.example.com/x", "version": 1},
    )
    assert r.status_code == 422


async def test_key_skills_are_cleaned_and_limited(client, user):
    h = user["headers"]
    r = await client.post(
        "/api/v1/profiles",
        headers=h,
        json={**VALID_PROFILE, "skills": ["Java", " java ", "Spring  Boot", "AWS"]},
    )
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["skills"] == ["Java", "Spring Boot", "AWS"]  # trimmed and de-duplicated

    twenty = [f"Skill {n}" for n in range(40)]  # the most a profile takes (2026-11-13: 40, was 20)
    r = await client.patch(f"/api/v1/profiles/{p['id']}", headers=h, json={"skills": twenty, "version": 1})
    assert r.status_code == 200 and r.json()["skills"] == twenty
    r = await client.patch(f"/api/v1/profiles/{p['id']}", headers=h, json={"skills": None, "version": 2})
    assert r.status_code == 200 and r.json()["skills"] == []

    r = await client.patch(
        f"/api/v1/profiles/{p['id']}", headers=h, json={"skills": [*twenty, "One too many"], "version": 3}
    )
    assert r.status_code == 422 and "up to 40 skills" in r.text
    r = await client.post(
        "/api/v1/profiles", headers=h, json={**VALID_PROFILE, "name": "X", "skills": ["x" * 41]}
    )
    assert r.status_code == 422 and "at most 40 characters" in r.text
    assert (await client.get("/api/v1/profiles/meta", headers=h)).json()["max_skills"] == 40
