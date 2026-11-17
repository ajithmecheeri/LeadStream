"""Duplicates (milestone 9.3): certain ones merged, possible ones flagged for the user, answers remembered."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.db import user_scope
from app.modules.catalog.models import Job
from app.modules.catalog.parsers import JobCard
from app.modules.catalog.service import upsert_cards
from app.modules.jobs.duplicates import View, classify, poster, title_words
from app.modules.jobs.linking import link_cards
from app.modules.jobs.models import UserJob
from app.modules.matching.models import JobMatch
from app.modules.networking.companies import company_key
from tests.test_notifications import alert, no_quiet_hours, verified

ABOUT = (
    "You will lead the platform engineering organisation of about sixty engineers across five teams, own the "
    "roadmap for the payments platform together with product, hire and grow engineering managers, and run "
    "delivery for a system that settles a billion transactions a month. You have built distributed systems at "
    "scale, managed managers, and partnered with business leaders on multi-year plans. Experience with cloud "
    "infrastructure, reliability practices and regulated environments is expected."
)


def view(title: str, company: str | None, location: str | None = "Bengaluru", **kw) -> View:
    return View(
        id=uuid4(),
        status="new",
        first_seen_at=datetime.now(UTC),
        title=title,
        company=company,
        location=location,
        experience=kw.pop("experience", None),
        description=kw.pop("description", None),
        sources=frozenset(kw.pop("sources", {"linkedin"})),
    )


@pytest.mark.nodb
def test_titles_are_compared_word_for_word_after_abbreviations():
    assert title_words("VP, Engineering") == title_words("Vice President - Engineering")
    assert title_words("Sr. Engg Manager") == title_words("Senior Engineering Manager")
    assert title_words("Director of Engineering") == title_words("Engineering Director")


@pytest.mark.nodb
def test_who_posted_it():
    assert poster("Acme Cloud Pvt Ltd") == "company"
    assert poster("Leading MNC") == "unnamed"
    assert poster("Confidential") == "unnamed"
    assert poster("A Leading Fintech Company") == "unnamed"
    assert poster(None) == "unnamed"
    assert poster("WhiteSlips Job Management Consultants") == "agency"
    assert poster("Crescendo Staffing") == "agency"
    assert poster("Tata Consultancy Services") == "company"


@pytest.mark.nodb
def test_same_company_title_and_city_is_certain():
    found = classify(
        view("VP Engineering", "Acme Cloud", "Bengaluru, Karnataka"),
        view("Vice President, Engineering", "Acme Cloud Pvt. Ltd.", "Bangalore"),
    )
    assert found and found.kind == "same"


@pytest.mark.nodb
def test_possible_duplicates_at_the_same_company():
    other_city = classify(view("VP Engineering", "Acme"), view("VP Engineering", "Acme", "Pune"))
    assert other_city and other_city.kind == "likely" and "another city" in other_city.reason
    similar = classify(
        view("Director Product Management", "Target", "Bengaluru East"),
        view("Director Product Management - Customer Data Platform", "Target", "Bengaluru"),
    )
    assert similar and similar.kind == "likely"
    # Another level is another job.
    assert classify(view("Engineering Manager", "Acme"), view("Senior Engineering Manager", "Acme")) is None
    assert classify(view("Director of Engineering", "Acme"), view("VP Engineering", "Acme")) is None


@pytest.mark.nodb
def test_two_named_companies_and_one_careers_site_are_never_duplicates():
    # Okta and Zscaler can share a description template.
    assert (
        classify(
            view("VP Engineering", "Okta", description=ABOUT),
            view("VP Engineering", "Zscaler", description=ABOUT),
        )
        is None
    )
    # Two listings on a company's own careers site are two openings.
    feed = {"greenhouse"}
    assert (
        classify(view("VP Engineering", "Acme", sources=feed), view("VP Engineering", "Acme", sources=feed))
        is None
    )


@pytest.mark.nodb
def test_an_agency_posting_needs_the_same_description_city_level_and_years():
    named = view("VP Engineering", "Acme Cloud", description=ABOUT, experience="15-20 years")
    agency = view(
        "VP - Engineering",
        "Leading MNC",
        description="Our client is hiring. " + ABOUT,
        experience="15-20 yrs",
    )
    found = classify(agency, named)
    assert found and found.kind == "agency" and found.similarity >= 90
    assert classify(view("VP - Engineering", "Leading MNC"), named) is None  # no description: no flag
    assert classify(view("VP - Engineering", "Leading MNC", "Pune", description=ABOUT), named) is None
    other_years = view("VP - Engineering", "Leading MNC", description=ABOUT, experience="8-12 years")
    assert classify(other_years, named) is None
    assert classify(view("Director of Engineering", "Leading MNC", description=ABOUT), named) is None


def card(
    title: str, company: str | None, location: str | None = "Bengaluru", source: str = "linkedin", **kw
) -> JobCard:
    n = uuid4().hex[:12]
    return JobCard(
        source=source,
        source_job_id=n,
        title=title,
        company=company,
        location=location,
        lead=kw.pop("lead", "alert"),
        canonical_url=f"https://jobs.example.com/{source}/{n}",
        **kw,
    )


async def link(user_id: UUID, *cards: JobCard) -> list[UUID]:
    async with user_scope(user_id) as db:
        return await link_cards(db, user_id, list(cards), await upsert_cards(db, list(cards)))


async def my_jobs(user_id: UUID) -> dict[str, UserJob]:
    async with user_scope(user_id) as db:
        rows = (await db.execute(select(UserJob, Job).join(Job, Job.id == UserJob.job_id))).all()
        return {f"{job.company}: {job.title}": uj for uj, job in rows}


async def detail(client, account, user_job_id) -> dict:
    r = await client.get(f"/api/v1/jobs/{user_job_id}", headers=account["headers"])
    assert r.status_code == 200, r.text
    return r.json()


async def answer(client, account, user_job_id, pair_id, same: bool):
    return await client.post(
        f"/api/v1/jobs/{user_job_id}/duplicates/{pair_id}", json={"same": same}, headers=account["headers"]
    )


async def listed(client, account, status: str = "active") -> list[dict]:
    r = await client.get(f"/api/v1/jobs?status={status}", headers=account["headers"])
    assert r.status_code == 200, r.text
    return r.json()["items"]


async def test_the_same_job_from_another_portal_is_merged_and_can_be_undone(client, account):
    uid = account["id"]
    (first,) = await link(uid, card("VP Engineering", "Acme Cloud"))
    added = await link(
        uid, card("Vice President, Engineering", "Acme Cloud Pvt. Ltd.", "Bangalore", source="naukri")
    )
    assert added == []  # merged at once: not a new job
    jobs = await my_jobs(uid)
    second = jobs["Acme Cloud Pvt. Ltd.: Vice President, Engineering"]
    assert second.status == "duplicate" and second.duplicate_of == first

    shown = await listed(client, account)
    assert [j["id"] for j in shown] == [str(first)]
    assert [j["id"] for j in await listed(client, account, "all")] == [str(first)]
    kept = await detail(client, account, first)
    (pair,) = kept["duplicates"]
    assert pair["merged"] == "into_this" and pair["kind"] == "same"
    assert pair["other"]["job"]["sources"][0]["source"] == "naukri"
    gone = await detail(client, account, second.id)
    assert gone["status"] == "duplicate" and gone["duplicate_of"] == str(first)
    assert gone["duplicates"][0]["merged"] == "into_other"

    # Not the same job: both are back, and the pair isn't flagged again.
    r = await answer(client, account, first, pair["id"], same=False)
    assert r.status_code == 200, r.text
    assert r.json()["duplicates"] == []
    assert {j["id"] for j in await listed(client, account)} == {str(first), str(second.id)}
    assert (await detail(client, account, second.id))["status"] == "seen"


async def test_a_possible_duplicate_is_flagged_and_same_job_keeps_the_applied_one(client, account):
    uid = account["id"]
    (applied,) = await link(uid, card("Director Product Management - Customer Data Platform", "Target"))
    job = await detail(client, account, applied)
    r = await client.patch(
        f"/api/v1/jobs/{applied}",
        json={"status": "applied", "version": job["version"]},
        headers=account["headers"],
    )
    assert r.status_code == 200, r.text
    (later,) = await link(uid, card("Director Product Management", "Target", "Bengaluru East"))

    flagged = {j["id"]: j["possible_duplicate"] for j in await listed(client, account, "all")}
    assert flagged == {str(applied): True, str(later): True}
    (pair,) = (await detail(client, account, later))["duplicates"]
    assert pair["kind"] == "likely" and pair["merged"] is None and pair["answer"] is None
    assert pair["other"]["status"] == "applied" and pair["other"]["applied_on"]

    r = await answer(client, account, later, pair["id"], same=True)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "duplicate" and r.json()["duplicate_of"] == str(applied)
    assert [j["id"] for j in await listed(client, account, "applied")] == [str(applied)]
    assert not (await detail(client, account, applied))["possible_duplicate"]


async def test_an_agency_posting_of_a_named_companys_job_is_flagged(client, account):
    uid = account["id"]
    (named,) = await link(
        uid, card("VP Engineering", "Acme Cloud", description=ABOUT, experience="15-20 years")
    )
    (agency,) = await link(
        uid,
        card(
            "VP - Engineering",
            "Leading MNC",
            source="naukri",
            lead="recruiter_invite",
            description="Our client, a leading MNC, is hiring. " + ABOUT,
            experience="15-20 years",
        ),
    )
    (pair,) = (await detail(client, account, agency))["duplicates"]
    assert pair["kind"] == "agency" and pair["other"]["id"] == str(named) and pair["similarity"] >= 90


async def test_listings_on_one_careers_site_are_not_compared(client, account):
    uid = account["id"]
    added = await link(
        uid,
        card("Solutions Architect", "Databricks", source="greenhouse", lead="company_feed"),
        card("Solutions Architect", "Databricks", "Mumbai", source="greenhouse", lead="company_feed"),
    )
    assert len(added) == 2
    assert not any(j["possible_duplicate"] for j in await listed(client, account))


async def test_no_alert_for_a_possible_duplicate_of_a_job_already_applied_to(client, account, monkeypatch):
    uid = account["id"]
    await verified(client, account, monkeypatch)
    await no_quiet_hours(uid)
    (applied,) = await link(uid, card("Director Product Management - Customer Data Platform", "Target"))
    job = await detail(client, account, applied)
    await client.patch(
        f"/api/v1/jobs/{applied}",
        json={"status": "applied", "version": job["version"]},
        headers=account["headers"],
    )
    (later,) = await link(uid, card("Director Product Management", "Target"))
    (fresh,) = await link(uid, card("Head of Product", "Other Co"))
    async with user_scope(uid) as db:
        for i in (later, fresh):
            db.add(JobMatch(user_job_id=i, user_id=uid, band="strong", score=90))
    assert await alert(uid, [later, fresh]) == 1


async def test_duplicate_errors(client, account):
    uid = account["id"]
    (first,) = await link(uid, card("VP Engineering", "Acme Cloud"))
    r = await answer(client, account, first, uuid4(), same=True)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    await link(uid, card("VP Engineering", "Acme Cloud", "Pune"))
    (pair,) = (await detail(client, account, first))["duplicates"]
    r = await client.post(
        f"/api/v1/jobs/{first}/duplicates/{pair['id']}", json={}, headers=account["headers"]
    )
    assert r.status_code == 422
    # Merging goes through Same job / Different job, not the status.
    job = await detail(client, account, first)
    r = await client.patch(
        f"/api/v1/jobs/{first}",
        json={"status": "duplicate", "version": job["version"]},
        headers=account["headers"],
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "duplicate"


@pytest.mark.nodb
def test_a_known_agency_is_compared_without_the_description():
    named = view("Director of Engineering", "Acme Cloud", experience="15-20 years")
    agency = view("Director - Engineering", "Crescendo Staffing", experience="15-20 years")
    assert classify(agency, named) is None  # no description to compare
    recruits = frozenset({(company_key("Crescendo Staffing"), company_key("Acme Cloud"))})
    found = classify(agency, named, recruits)
    assert found and found.kind == "agency" and "recruits for Acme Cloud" in found.reason
    assert classify(view("Director - Engineering", "Crescendo Staffing", "Pune"), named, recruits) is None


async def test_same_job_on_an_agency_pair_is_remembered_for_its_next_postings(client, account):
    uid = account["id"]
    await link(uid, card("VP Engineering", "Acme Cloud", description=ABOUT, experience="15-20 years"))
    (agency,) = await link(
        uid,
        card(
            "VP - Engineering",
            "Crescendo Staffing",
            source="naukri",
            description=ABOUT,
            experience="15-20 years",
        ),
    )
    (pair,) = (await detail(client, account, agency))["duplicates"]
    assert pair["kind"] == "agency"
    assert (await answer(client, account, agency, pair["id"], same=True)).status_code == 200

    # A month later: the company posts another role, and the agency posts it with a one-line description.
    (role,) = await link(uid, card("Director of Data Engineering", "Acme Cloud", experience="12-16 years"))
    (again,) = await link(
        uid,
        card("Director - Data Engineering", "Crescendo Staffing", source="naukri", experience="12-16 years"),
    )
    (pair,) = (await detail(client, account, again))["duplicates"]
    assert pair["kind"] == "agency" and pair["other"]["id"] == str(role)
    assert "recruits for Acme Cloud" in pair["reason"]
