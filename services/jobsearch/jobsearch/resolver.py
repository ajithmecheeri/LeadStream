"""Finding an employer's job board from a careers link or a name (moved from the main app's sources/discover.py).

A link names its hiring system and board directly (Greenhouse, Lever, Ashby, SmartRecruiters, Workday, Oracle,
Eightfold); any other company link is read as a careers site (step 2); a job portal's link is refused. A name is
tried as a board id on the four systems with public APIs. Workday, Oracle, Eightfold and careers sites are found
by link only (decisions 5 and 12 in docs/plan-jobsearch-build.md).
"""

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from jobsearch.connectors import BoardNotFound, careers, client, eightfold, feeds, fetch_board, oracle
from jobsearch.connectors.workday import Board as WorkdayBoard

_HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "boards.eu.greenhouse.io": "greenhouse",
    "job-boards.eu.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
    "jobs.smartrecruiters.com": "smartrecruiters",
    "careers.smartrecruiters.com": "smartrecruiters",
}
BOARD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_SUFFIXES = re.compile(
    r"\b(inc|incorporated|ltd|limited|llc|corp|corporation|pvt|private|technologies|technology|labs|india|software"
    r"|solutions|co)\b\.?",
    re.I,
)


@dataclass(frozen=True)
class Found:
    system: str
    board: str
    in_scope: int  # jobs in the service's country on the board now
    total: int
    sample: list[str]  # a few in-scope job titles, so the user can tell it's the right company


# Checked 2026-11-03: public boards with senior roles in India (docs/plan-m9.md, decision 8).
SUGGESTED: list[tuple[str, str, str]] = [
    ("Databricks", "greenhouse", "databricks"),
    ("Okta", "greenhouse", "okta"),
    ("Zscaler", "greenhouse", "zscaler"),
    ("MongoDB", "greenhouse", "mongodb"),
    ("GitLab", "greenhouse", "gitlab"),
    ("Stripe", "greenhouse", "stripe"),
    ("Rubrik", "greenhouse", "rubrik"),
    ("Twilio", "greenhouse", "twilio"),
    ("Coinbase", "greenhouse", "coinbase"),
    ("Meesho", "lever", "meesho"),
    ("Zeta", "lever", "zeta"),
    ("Paytm", "lever", "paytm"),
    ("Freshworks", "smartrecruiters", "freshworks"),
    ("ServiceNow", "smartrecruiters", "servicenow"),
    ("Swiggy", "smartrecruiters", "swiggy"),
    ("Wise", "smartrecruiters", "wise"),
    # Workday (step 1): checked 2026-11-14, a public career site with India jobs.
    ("NVIDIA", "workday", "nvidia.wd5.myworkdayjobs.com/nvidia/NVIDIAExternalCareerSite"),
    # Step 2: checked 2026-11-14, public career sites with India jobs.
    ("JPMorgan Chase", "oracle", "jpmc.fa.oraclecloud.com/CX_1001"),
    ("Netflix", "eightfold", "explore.jobs.netflix.net/netflix.com"),
    ("Arm", "careers_page", "careers.arm.com"),
]


def is_portal_link(text: str) -> bool:
    t = text.strip()
    return careers.is_portal(urlsplit(t if "://" in t else "https://" + t).hostname or "")


def from_link(text: str) -> tuple[str, str] | None:
    """(system, board) from a board, job or careers link such as https://jobs.lever.co/acme/123, or None. A
    company's own careers site becomes a careers_page board; a job portal's link is refused (None)."""
    if is_portal_link(text):
        return None
    if wd := WorkdayBoard.from_url(text):
        return ("workday", wd.key)
    if orc := oracle.Board.from_url(text):
        return ("oracle", orc.key)
    if ef := eightfold.Board.from_url(text):
        return ("eightfold", ef.key)
    t = text.strip()
    if "://" not in t:
        t = "https://" + t
    parts = urlsplit(t)
    host = (parts.hostname or "").lower()
    system = _HOSTS.get(host)
    segments = [s for s in parts.path.split("/") if s]
    if system:
        if not segments:
            return None
        board = segments[0]
        if (
            system == "greenhouse" and board == "embed" and "for=" in parts.query
        ):  # /embed/job_board?for=<board>
            board = parts.query.split("for=")[1].split("&")[0]
        return (system, board) if BOARD_ID.match(board) else None
    if re.search(
        r"(myworkdayjobs|myworkdaysite|oraclecloud|eightfold\.ai|greenhouse\.io|lever\.co|ashbyhq|smartrecruiters)",
        host,
    ):
        return None  # a hiring system's address we couldn't read a board from
    site = careers.Site.from_url(text)
    return ("careers_page", site.key) if site else None


def valid_board(system: str, board: str) -> bool:
    try:
        if system == "workday":
            return WorkdayBoard.from_url(WorkdayBoard.parse(board).careers_url) is not None
        if system == "oracle":
            return oracle.Board.from_url(oracle.Board.parse(board).careers_url) is not None
        if system == "eightfold":
            b = eightfold.Board.parse(board)
            return bool(re.match(r"^([a-z0-9-]+\.)+[a-z]{2,}$", b.host))
        if system == "careers_page":
            site = careers.Site.parse(board)
            return careers.Site.from_url(site.url) == site
    except ValueError:
        return False
    return system in feeds.SYSTEMS and bool(BOARD_ID.match(board))


def board_guesses(name: str) -> list[str]:
    """Likely board ids for a company name: "Zeta Suite Pvt Ltd" → zetasuite, zeta-suite, zeta."""
    base = _SUFFIXES.sub(" ", name.lower())
    words = re.findall(r"[a-z0-9]+", base)
    if not words:
        return []
    guesses = ["".join(words), "-".join(words), words[0]]
    return [g for i, g in enumerate(guesses) if g and g not in guesses[:i] and BOARD_ID.match(g)]


LOOKUP_PAGES = 5  # a careers site's job pages read to show what it has


async def _try(http: httpx.AsyncClient, system: str, board: str) -> Found | None:
    # A quick look: no details, except a few careers pages (their titles are only on the pages).
    looks = LOOKUP_PAGES if system == "careers_page" else 0
    try:
        result = await fetch_board(system, board, board, http, max_details=looks)
    except (BoardNotFound, httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    if result.total == 0:
        return None
    titles = [p.title for p in result.postings if p.title][:3]
    # A careers site's India count is only known once its pages are read: what this look found.
    return Found(system, board, len(result.postings), result.total, titles)


async def lookup(query: str) -> list[Found]:
    """Every board that matches the link or name, best first (most in-scope jobs)."""
    is_link = "/" in query or "." in query
    link = from_link(query) if is_link else None
    if link:
        pairs = [link]
    elif is_link:
        return []
    else:
        pairs = [(system, b) for b in board_guesses(query) for system in feeds.SYSTEMS]
    async with client() as http:
        found = await asyncio.gather(*(_try(http, s, b) for s, b in pairs))
    unique = {(f.system, f.board.lower()): f for f in found if f}
    return sorted(unique.values(), key=lambda f: (-f.in_scope, -f.total))
