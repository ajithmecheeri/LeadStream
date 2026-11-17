"""The listings store: NEW, UPDATED, REPOSTED and CLOSED, versions, and Workday's pending postings."""

from dataclasses import replace

from sqlalchemy import func, select

from jobsearch import store
from jobsearch.connectors import BoardResult, Posting
from jobsearch.db import sessionmaker
from jobsearch.models import Event, Listing, ListingVersion
from jobsearch.service import register


def job(n: int = 1, **kw) -> Posting:
    base = dict(
        source="greenhouse",
        source_job_id=f"g-{n}",
        title=f"Director of Engineering {n}",
        company="Acme",
        location="Bengaluru, India",
        description="Lead the platform teams.",
        requisition_id=f"R-{n}",
    )
    return Posting(**{**base, **kw})


async def read(
    postings: list[Posting], complete: bool = True, system="greenhouse", board="acme"
) -> store.Counts:
    async with sessionmaker()() as db, db.begin():
        reg = await register(db, "Acme", system, board)
        return await store.record_board(db, reg.employer, reg.board, BoardResult(postings, 10, complete))


async def kinds() -> list[str]:
    async with sessionmaker()() as db:
        return list(await db.scalars(select(Event.type).order_by(Event.id)))


async def test_a_new_posting_is_announced_once():
    first = await read([job(1), job(2)])
    assert (first.found, first.new) == (2, 2)
    again = await read([job(1), job(2)])
    assert (again.new, again.updated, again.events) == (0, 0, [])
    assert await kinds() == ["NEW", "NEW"]


async def test_changed_content_is_an_update_with_the_old_version_kept():
    await read([job(1)])
    counts = await read([job(1, description="Lead the platform and data teams.")])
    assert counts.updated == 1
    async with sessionmaker()() as db:
        listing = await db.scalar(select(Listing))
        old = await db.scalar(select(ListingVersion))
    assert listing.version == 2 and listing.description == "Lead the platform and data teams."
    assert old.version == 1 and old.snapshot["description"] == "Lead the platform teams."
    assert await kinds() == ["NEW", "UPDATED"]


async def test_a_missing_fact_is_not_a_change():
    await read([job(1, salary="₹1 Cr")])
    counts = await read([job(1, salary=None, description=None)])  # e.g. a details call that failed once
    assert counts.updated == 0
    async with sessionmaker()() as db:
        listing = await db.scalar(select(Listing))
    assert listing.salary == "₹1 Cr" and listing.description == "Lead the platform teams."


async def test_a_posting_missing_twice_is_closed_and_reposted_when_it_returns():
    await read([job(1), job(2)])
    once = await read([job(1)])
    assert once.closed == 0  # one miss isn't enough
    twice = await read([job(1)])
    assert twice.closed == 1
    back = await read([job(1), job(2)])
    assert back.reposted == 1
    assert await kinds() == ["NEW", "NEW", "CLOSED", "REPOSTED"]


async def test_an_incomplete_read_closes_nothing():
    await read([job(1), job(2)])
    await read([job(1)], complete=False)
    counts = await read([job(1)], complete=False)
    assert counts.closed == 0


async def test_the_same_requisition_under_a_new_id_is_a_repost_of_the_closed_listing():
    await read([job(1)])
    await read([])
    await read([])  # closed
    counts = await read([job(1, source_job_id="g-1-new")])
    assert (counts.new, counts.reposted) == (0, 1)
    async with sessionmaker()() as db:
        assert await db.scalar(select(func.count()).select_from(Listing)) == 1


async def test_a_workday_posting_waits_for_its_details():
    stub = job(
        1, source="workday", source_job_id="/job/India-Pune/X_JR1", description=None, needs_details=True
    )
    first = await read([stub], system="workday", board="acme.wd5.myworkdayjobs.com/acme/Careers")
    assert (first.new, first.pending) == (0, 1)
    full = replace(stub, description="Build GPUs.", needs_details=False)
    second = await read([full], system="workday", board="acme.wd5.myworkdayjobs.com/acme/Careers")
    assert second.new == 1
    # Known postings come back without details: still the same listing, nothing to announce.
    third = await read([stub], system="workday", board="acme.wd5.myworkdayjobs.com/acme/Careers")
    assert (third.new, third.updated) == (0, 0)
    async with sessionmaker()() as db:
        listing = await db.scalar(select(Listing))
        board_id = listing.board_id
        from jobsearch.models import EmployerBoard

        board = await db.get(EmployerBoard, board_id)
        assert await store.known_ids(db, board) == {"/job/India-Pune/X_JR1"}
    assert listing.description == "Build GPUs." and listing.status == "active"
