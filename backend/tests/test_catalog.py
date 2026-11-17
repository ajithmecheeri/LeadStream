"""The shared job catalog: dedupe across emails, portals and concurrent workers, and merging facts."""

import asyncio
from dataclasses import replace
from pathlib import Path

from sqlalchemy import func, select

from app.core.db import sessionmaker
from app.modules.catalog.models import Job, JobSource
from app.modules.catalog.parsers import JobCard, parse_email
from app.modules.catalog.service import card_fingerprint, upsert_cards

EMAILS = Path(__file__).parent / "fixtures" / "emails"


def cards_of(name: str) -> list[JobCard]:
    return parse_email((EMAILS / name).read_bytes()).cards


async def upsert(cards: list[JobCard]):
    async with sessionmaker()() as db, db.begin():
        return await upsert_cards(db, cards)


async def counts() -> tuple[int, int]:
    async with sessionmaker()() as db:
        jobs = await db.scalar(select(func.count()).select_from(Job))
        sources = await db.scalar(select(func.count()).select_from(JobSource))
        return jobs, sources


async def get_job(job_id) -> Job:
    async with sessionmaker()() as db:
        return await db.get(Job, job_id)


LINKEDIN = "linkedin-alert-vice-president-bangalore-2026-10-29.eml"
NAUKRI = "naukri-alert-recommended-jobs-2026-09-21.eml"
INVITE = "naukri-recruiter-invite-vp-ai-2026-09-18.eml"


async def test_new_cards_create_jobs_and_sources():
    matches = await upsert(cards_of(LINKEDIN))

    assert [m.created for m in matches] == [True] * 6
    assert await counts() == (6, 6)
    job = await get_job(matches[4].job_id)
    assert (job.title, job.company, job.work_model, job.salary) == (
        "Professional Services Leader - India",
        "FirstApex",
        "Remote",
        "₹5M-₹6M / year",
    )
    assert job.fingerprint is not None and job.description_complete is False


async def test_the_same_alert_twice_adds_nothing():
    first = await upsert(cards_of(LINKEDIN))
    again = await upsert(cards_of(LINKEDIN))

    assert [m.job_id for m in again] == [m.job_id for m in first]
    assert [m.created for m in again] == [False] * 6
    assert await counts() == (6, 6)


async def test_a_job_seen_on_two_portals_is_one_job_with_two_sources():
    linkedin = cards_of(LINKEDIN)[2]  # SEG & India CFO · Cognizant · Bangalore Urban
    naukri = JobCard(
        source="naukri",
        source_job_id="111111111111",
        title="SEG & India CFO",
        company="Cognizant Pvt. Ltd.",  # the fingerprint ignores company suffixes and punctuation
        location="Bangalore Urban",
        lead="recommendation",
        canonical_url="https://www.naukri.com/jd/job-listings-seg-india-cfo-cognizant-111111111111",
        experience="20-25 years",
    )
    (a,) = await upsert([linkedin])
    (b,) = await upsert([naukri])

    assert b.job_id == a.job_id and b.created is False
    assert await counts() == (1, 2)
    job = await get_job(a.job_id)
    assert job.experience == "20-25 years"  # filled in from Naukri
    assert job.work_model == "Hybrid"  # kept from LinkedIn


async def test_cut_off_company_names_never_merge_by_fingerprint():
    card = JobCard(
        source="naukri",
        source_job_id="1",
        title="Head of AI",
        company="Acme Glob...",
        company_truncated=True,
        location="Pune",
        lead="recommendation",
    )
    a, b = await upsert([card, replace(card, source_job_id="2")])

    assert a.job_id != b.job_id
    job = await get_job(a.job_id)
    assert job.fingerprint is None and job.details == {"company_truncated": True}


async def test_full_company_name_replaces_a_cut_off_one():
    cut = JobCard(
        source="naukri",
        source_job_id="1",
        title="Head of AI",
        company="Acme Glob...",
        company_truncated=True,
        location="Pune",
        lead="recommendation",
    )
    (a,) = await upsert([cut])
    (b,) = await upsert([replace(cut, company="Acme Global", company_truncated=False)])

    assert b.job_id == a.job_id
    job = await get_job(a.job_id)
    assert job.company == "Acme Global" and "company_truncated" not in job.details
    assert job.fingerprint is not None  # now that the name is known, the job can match other portals


async def test_recruiter_invite_has_no_public_url_and_keeps_its_description():
    (a,) = await upsert(cards_of(INVITE))
    (again,) = await upsert(cards_of(INVITE))

    assert again.job_id == a.job_id
    assert await counts() == (1, 1)
    job = await get_job(a.job_id)
    assert job.company is None and job.fingerprint is None
    assert job.description_complete is True and job.description.startswith("Roles and Responsibilities")
    assert job.details["industry"] == "FMCG"
    async with sessionmaker()() as db:
        source = (await db.execute(select(JobSource))).scalar_one()
    assert (source.source, source.source_job_id, source.url) == ("naukri_rdx", "180926021094", None)


async def test_a_full_description_fills_a_partial_job_once():
    card = cards_of(LINKEDIN)[0]
    (a,) = await upsert([card])
    await upsert([replace(card, description="Full description")])
    await upsert([replace(card, description="A later, different description")])

    job = await get_job(a.job_id)
    assert (job.description, job.description_complete) == ("Full description", True)


async def test_nothing_about_the_recipient_reaches_the_catalog():
    await upsert(cards_of(LINKEDIN) + cards_of(NAUKRI) + cards_of(INVITE))
    async with sessionmaker()() as db:
        jobs = (await db.execute(select(Job))).scalars().all()
        urls = (await db.execute(select(JobSource.url))).scalars().all()
    assert all("connection" not in str(j.details) and "Easy Apply" not in str(j.details) for j in jobs)
    assert all("?" not in u for u in urls if u)  # no tracking or login tokens
    assert not any("applyBroadcastMail" in str(j.details) for j in jobs)


async def test_concurrent_workers_do_not_duplicate_a_job():
    cards = cards_of(NAUKRI)
    results = await asyncio.gather(upsert(cards), upsert(cards), upsert(list(reversed(cards))))

    assert await counts() == (11, 11)
    ids = [sorted(m.job_id for m in r) for r in results]
    assert ids[0] == ids[1] == ids[2]
    assert sum(m.created for r in results for m in r) == 11


async def upsert_unverified(cards: list[JobCard]):
    async with sessionmaker()() as db, db.begin():
        return await upsert_cards(db, cards, verified=False)


async def test_a_hand_forwarded_card_never_changes_a_known_job():
    real = cards_of(LINKEDIN)[0]
    (known,) = await upsert([real])
    (forwarded,) = await upsert_unverified([replace(real, title="Made-up title", salary="₹9 crore")])

    assert forwarded.job_id == known.job_id and not forwarded.created
    job = await get_job(known.job_id)
    assert (job.title, job.salary, job.verified) == (real.title, real.salary, True)


async def test_a_verified_card_replaces_a_hand_forwarded_job():
    real = cards_of(LINKEDIN)[0]
    (forwarded,) = await upsert_unverified([replace(real, title="Made-up title", salary="₹9 crore")])
    assert (await get_job(forwarded.job_id)).verified is False

    (verified,) = await upsert([real])
    assert verified.job_id == forwarded.job_id
    job = await get_job(verified.job_id)
    assert (job.title, job.salary, job.verified) == (real.title, real.salary, True)
    assert job.fingerprint == card_fingerprint(real)
