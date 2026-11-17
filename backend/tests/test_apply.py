"""Milestone 14.1–14.2: the apply profile (what forms ask beyond the candidate profile) and a job's Apply kit."""

import pytest

from app.modules.apply.service import draft, education, month
from tests import samples
from tests.test_duplicates import card, link

PROFILE = {
    "phone": "+91 90000 00001",
    "address_line1": "12 Example Road",
    "city": "Bengaluru",
    "state": "Karnataka",
    "postal_code": "560001",
    "country": "India",
    "websites": ["https://priya.example.com"],
    "languages": [{"language": "English", "proficiency": "fluent"}, {"language": "Malayalam"}],
    "work_history": [
        {"title": "VP, Engineering", "company": "Example Fintech", "start": "2021-01", "current": True},
        {
            "title": "Director, Engineering",
            "company": "Sample Retail Tech",
            "start": "2015-03",
            "end": "2020-12",
        },
    ],
    "education": [{"school": "Example Institute of Technology", "degree": "B.Tech", "end_year": 2004}],
}


@pytest.mark.nodb
def test_months_and_education_lines():
    assert month("Jan 2021") == "2021-01" and month("Sept 2015") == "2015-09" and month("2004") == "2004-01"
    assert month("Present") is None
    (iit,) = education(["MBA, Finance | Indian Institute of Management Bangalore | 2010 – 2012"])
    assert (iit.school, iit.degree, iit.field, iit.start_year, iit.end_year) == (
        "Indian Institute of Management Bangalore",
        "MBA",
        "Finance",
        2010,
        2012,
    )
    assert education(["PMP certification"]) == []  # neither a school nor a degree
    assert education(["MBA, Finance 2012"]) == []  # no school named: left for the user


@pytest.mark.nodb
def test_a_resume_proposes_work_history_and_education():
    d = draft(samples.RESUME)
    assert (d.phone, d.city) == ("+91 90000 00001", "Bengaluru")
    assert [(w.title, w.company, w.start, w.end, w.current) for w in d.work_history] == [
        ("VP, Engineering", "Example Fintech Pvt Ltd", "2021-01", None, True),
        ("Director, Engineering", "Sample Retail Tech", "2015-03", "2020-12", False),
        ("Senior Software Engineer", "Demo Systems", "2004-06", "2015-02", False),
    ]
    (edu,) = d.education
    assert (edu.school, edu.degree, edu.field, edu.start_year, edu.end_year) == (
        "Example Institute of Technology",
        "B.Tech",
        "Computer Science",
        2000,
        2004,
    )


async def test_save_the_apply_profile_with_versions(client, account):
    h = account["headers"]
    empty = (await client.get("/api/v1/apply-profile", headers=h)).json()
    assert empty["version"] == 0 and empty["work_history"] == []
    r = await client.put("/api/v1/apply-profile", json={**PROFILE, "version": 0}, headers=h)
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["version"] == 1 and saved["work_history"][0]["current"] is True
    assert saved["websites"] == ["https://priya.example.com/"]
    r = await client.put("/api/v1/apply-profile", json={**PROFILE, "phone": "+91 1", "version": 0}, headers=h)
    assert r.status_code == 409
    r = await client.put("/api/v1/apply-profile", json={**PROFILE, "city": "Pune", "version": 1}, headers=h)
    assert r.json()["city"] == "Pune" and r.json()["version"] == 2


async def test_apply_profile_errors(client, account):
    h = account["headers"]
    bad = {**PROFILE, "work_history": [{"title": "VP", "start": "2021-13"}], "version": 0}
    r = await client.put("/api/v1/apply-profile", json=bad, headers=h)
    assert r.status_code == 422
    assert "work_history" in r.json()["error"]["details"][0]["field"]
    r = await client.post(
        "/api/v1/apply-profile/from-resume",
        json={"resume_id": "00000000-0000-0000-0000-000000000000"},
        headers=h,
    )
    assert r.status_code == 404


async def test_a_resume_fills_the_draft(client, account):
    h = account["headers"]
    resume = (
        await client.post("/api/v1/resumes", json={"text": samples.RESUME, "label": "Cloud"}, headers=h)
    ).json()
    r = await client.post("/api/v1/apply-profile/from-resume", json={"resume_id": resume["id"]}, headers=h)
    assert r.status_code == 200, r.text
    work = r.json()["work_history"]
    assert len(work) == 3
    assert work[0]["current"] is True
    # The lines under a role are its description, up to the next role (never the next section).
    assert (
        work[0]["description"]
        == "Built an AI platform on AWS with LLM-based document processing for lending."
    )
    assert work[2]["description"] == "Built Java and .NET services for a wealth management client."
    assert (await client.get("/api/v1/apply-profile", headers=h)).json()["version"] == 0  # nothing saved


async def test_the_apply_kit_lists_fields_in_workday_order(client, account):
    h = account["headers"]
    await client.put("/api/v1/apply-profile", json={**PROFILE, "version": 0}, headers=h)
    await client.put("/api/v1/answers/notice_period", json={"answer": "60 days"}, headers=h)
    resume = (
        await client.post("/api/v1/resumes", json={"text": samples.RESUME, "label": "Cloud"}, headers=h)
    ).json()
    (job,) = await link(account["id"], card("VP Engineering", "Acme"))

    r = await client.get(f"/api/v1/jobs/{job}/apply-kit", headers=h)
    assert r.status_code == 200, r.text
    kit = r.json()
    assert [s["title"] for s in kit["sections"]] == [
        "My information",
        "My experience",
        "Application questions",
    ]
    info = {f["key"]: f["value"] for f in kit["sections"][0]["fields"]}
    assert info["phone"] == "+91 90000 00001" and info["postal_code"] == "560001"
    assert info["email"] == (await client.get("/api/v1/me", headers=h)).json()["email"]
    exp = {f["key"]: f["value"] for f in kit["sections"][1]["fields"]}
    assert exp["work.0.to"] == "I currently work here" and exp["work.1.from"] == "Mar 2015"
    assert exp["languages"] == "English (fluent), Malayalam"
    questions = {f["key"]: f["value"] for f in kit["sections"][2]["fields"]}
    assert questions["answer:notice_period"] == "60 days"
    assert kit["documents"] == [{"id": resume["id"], "label": "Cloud", "kind": "resume"}]
    assert kit["missing"] == []


async def test_the_apply_kit_says_what_is_missing(client, account):
    (job,) = await link(account["id"], card("VP Engineering", "Acme"))
    kit = (await client.get(f"/api/v1/jobs/{job}/apply-kit", headers=account["headers"])).json()
    assert kit["missing"] == ["Phone", "Address", "Work history", "Education"] and kit["documents"] == []
    r = await client.get(
        "/api/v1/jobs/00000000-0000-0000-0000-000000000000/apply-kit", headers=account["headers"]
    )
    assert r.status_code == 404
