"""Checking boards and job APIs. HTTP happens outside database transactions; each board is stored on its own,
so one failing never stops the others."""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from jobsearch import store
from jobsearch.config import get_settings
from jobsearch.connectors import DETAILED, BoardNotFound, adzuna, client, fetch_board
from jobsearch.db import sessionmaker
from jobsearch.models import ApiQuota, ConnectorRun, Employer, EmployerBoard, SearchArea

log = logging.getLogger("jobsearch")


@dataclass(frozen=True)
class Registered:
    employer: Employer
    board: EmployerBoard
    created: bool


async def register(
    db: AsyncSession, name: str, system: str, board: str, employer_id: UUID | None = None
) -> Registered:
    """The employer for this board, created when new. Two callers at once: the unique index keeps one row."""
    existing = await db.scalar(
        select(EmployerBoard).where(
            EmployerBoard.system == system, func.lower(EmployerBoard.board) == board.lower()
        )
    )
    if existing is not None:
        return Registered(await db.get(Employer, existing.employer_id), existing, False)
    employer = Employer(name=name.strip() or board, country=get_settings().country)
    if employer_id is not None:
        employer.id = employer_id
    db.add(employer)
    await db.flush()
    stmt = (
        insert(EmployerBoard)
        .values(employer_id=employer.id, system=system, board=board)
        .on_conflict_do_nothing(index_elements=[EmployerBoard.system, func.lower(EmployerBoard.board)])
        .returning(EmployerBoard.id)
    )
    board_id = await db.scalar(stmt)
    if board_id is None:  # lost the race: use the other caller's rows
        await db.delete(employer)
        row = await db.scalar(
            select(EmployerBoard).where(
                EmployerBoard.system == system, func.lower(EmployerBoard.board) == board.lower()
            )
        )
        return Registered(await db.get(Employer, row.employer_id), row, False)
    return Registered(employer, await db.get(EmployerBoard, board_id), True)


async def check_board(board_id: UUID, http: httpx.AsyncClient | None = None) -> ConnectorRun:
    """Read one board now and store what changed. Never raises for a board that's down or gone."""
    async with sessionmaker()() as db:
        board = await db.get(EmployerBoard, board_id)
        if board is None:
            raise LookupError(board_id)
        employer = await db.get(Employer, board.employer_id)
        known = await store.known_ids(db, board) if board.system in DETAILED else set()
        skip = await store.skipped_pages(db, board) if board.system == "careers_page" else set()
        system, key, name = board.system, board.board, employer.name
    started = datetime.now(UTC)
    error, result = None, None
    own = http is None
    http = http or client()
    try:
        result = await fetch_board(system, key, name, http, known, skip=skip)
    except BoardNotFound:
        error = f"No job board '{key}' on {system.capitalize()} any more"
    except httpx.HTTPError as e:
        error = f"{system.capitalize()} didn't answer ({type(e).__name__})"
    finally:
        if own:
            await http.aclose()

    async with sessionmaker()() as db, db.begin():
        board = await db.get(EmployerBoard, board_id)
        employer = await db.get(Employer, board.employer_id)
        run = ConnectorRun(connector=system, board_id=board_id, started_at=started)
        if result is None:
            board.last_checked_at, board.last_error = datetime.now(UTC), error
            run.error = error
        else:
            counts = await store.record_board(db, employer, board, result)
            await store.remember_pages(db, board, result.out_of_scope)
            for k in ("found", "new", "updated", "reposted", "closed", "pending"):
                setattr(run, k, getattr(counts, k))
        run.finished_at = datetime.now(UTC)
        db.add(run)
    log.info("board %s/%s: %s", system, key, error or f"found {run.found}, new {run.new}")
    return run


async def due_boards() -> list[UUID]:
    """Every board, least recently checked first. Each is checked once, however many users follow it."""
    async with sessionmaker()() as db:
        rows = await db.scalars(
            select(EmployerBoard.id).order_by(EmployerBoard.last_checked_at.asc().nulls_first())
        )
        return list(rows)


async def _take_quota(db: AsyncSession, api: str, limit: int) -> bool:
    """Count one call against today's quota; False (and nothing counted) once it is used up."""
    today = date.today()
    used = await db.scalar(select(ApiQuota.calls).where(ApiQuota.api == api, ApiQuota.day == today)) or 0
    if used >= limit:
        return False
    await db.execute(
        insert(ApiQuota)
        .values(api=api, day=today, calls=1)
        .on_conflict_do_update(
            index_elements=[ApiQuota.api, ApiQuota.day], set_={"calls": ApiQuota.calls + 1}
        )
    )
    return True


async def run_apis(http: httpx.AsyncClient | None = None) -> list[ConnectorRun]:
    """Search the job APIs for each active search area (least recently searched first), within the quota."""
    if not adzuna.configured():
        return []
    async with sessionmaker()() as db:
        areas = list(
            await db.scalars(
                select(SearchArea)
                .where(SearchArea.active)
                .order_by(SearchArea.last_api_run_at.asc().nulls_first())
            )
        )
    runs = []
    own = http is None
    http = http or client()
    try:
        for area in areas:
            postings, error = [], None
            started = datetime.now(UTC)
            for title in dict.fromkeys(area.titles or [area.role_family]):
                async with sessionmaker()() as db, db.begin():
                    allowed = await _take_quota(db, "adzuna", get_settings().adzuna_daily_calls)
                if not allowed:
                    error = "Daily Adzuna quota used up"
                    break
                try:
                    postings += await adzuna.search(title, area.location, http)
                except httpx.HTTPError as e:
                    error = f"Adzuna didn't answer ({type(e).__name__})"
            async with sessionmaker()() as db, db.begin():
                counts = await store.record_search(db, postings)
                run = ConnectorRun(
                    connector="adzuna", search_area_id=area.id, started_at=started, error=error
                )
                for k in ("found", "new", "updated", "reposted"):
                    setattr(run, k, getattr(counts, k))
                run.finished_at = datetime.now(UTC)
                db.add(run)
                row = await db.get(SearchArea, area.id)
                row.last_api_run_at = datetime.now(UTC)
            runs.append(run)
            if error == "Daily Adzuna quota used up":
                break
    finally:
        if own:
            await http.aclose()
    return runs
