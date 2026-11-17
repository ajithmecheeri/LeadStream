"""Connectors: one reader per hiring system or job API. `fetch_board` reads one employer board."""

import httpx

from jobsearch.connectors import careers, eightfold, feeds, oracle, workday
from jobsearch.connectors.base import BoardNotFound, BoardResult, Posting, client

__all__ = ["BoardNotFound", "BoardResult", "Posting", "client", "fetch_board", "board_url", "DETAILED"]

_BOARD_URL = {
    "greenhouse": "https://boards.greenhouse.io/{}",
    "lever": "https://jobs.lever.co/{}",
    "ashby": "https://jobs.ashbyhq.com/{}",
    "smartrecruiters": "https://careers.smartrecruiters.com/{}",
}
# Systems whose postings are listed first and read in detail later (the store keeps which were read).
DETAILED = ("workday", "oracle", "eightfold", "careers_page")


def board_url(system: str, board: str) -> str:
    if system == "workday":
        return workday.Board.parse(board).careers_url
    if system == "oracle":
        return oracle.Board.parse(board).careers_url
    if system == "eightfold":
        return eightfold.Board.parse(board).careers_url
    if system == "careers_page":
        return careers.Site.parse(board).url
    return _BOARD_URL[system].format(board)


async def fetch_board(
    system: str,
    board: str,
    company: str,
    http: httpx.AsyncClient,
    known: set[str] | None = None,
    max_details: int | None = None,
    skip: set[str] | None = None,
) -> BoardResult:
    """The board's postings in scope. `known`: postings already read in detail (not read again); `max_details`:
    at most this many detail reads (0 for a quick look); `skip`: careers pages found out of scope before.
    Raises BoardNotFound, or httpx errors when the system is down."""
    known = known or set()
    if system == "workday":
        return await workday.fetch(workday.Board.parse(board), company, http, known, max_details)
    if system == "oracle":
        return await oracle.fetch(oracle.Board.parse(board), company, http, known, max_details)
    if system == "eightfold":
        return await eightfold.fetch(eightfold.Board.parse(board), company, http, known, max_details)
    if system == "careers_page":
        return await careers.fetch(careers.Site.parse(board), company, http, known, skip, max_details)
    return await feeds.fetch(system, board, company, http)
