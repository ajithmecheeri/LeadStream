"""What every connector produces, and the helpers they share."""

import html
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from bs4 import BeautifulSoup

from jobsearch import locations

USER_AGENT = "BrewMyJob/1.0 (+https://brewmyjob.com)"
TIMEOUT = 20.0


@dataclass(frozen=True)
class Posting:
    """One job as a source lists it, normalised. Unknown values stay empty; nothing is guessed."""

    source: str  # greenhouse | lever | ashby | smartrecruiters | workday | adzuna
    source_job_id: str
    title: str
    company: str | None
    location: str | None
    url: str | None = None
    apply_url: str | None = None
    work_model: str | None = None  # Remote | Hybrid | On-site
    salary: str | None = None
    experience: str | None = None
    skills: tuple[str, ...] = ()
    description: str | None = None
    details: dict[str, str] = field(default_factory=dict)
    posted_at: datetime | None = None
    requisition_id: str | None = None
    # Workday lists postings without their description; True until the details are read.
    needs_details: bool = False


@dataclass(frozen=True)
class BoardResult:
    postings: list[Posting]  # in scope (the service's country) only
    total: int  # every posting on the board, anywhere
    complete: bool = True  # the whole board was read (a posting missing from it may have closed)
    # Careers pages read now and found outside the service's country (or not a job): not read again for a while.
    out_of_scope: tuple[str, ...] = ()


class BoardNotFound(Exception):
    """The board doesn't exist on that hiring system (or shows no postings)."""


def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


def text_of(markup: str | None) -> str | None:
    """Plain text from a posting's HTML, paragraphs kept."""
    if not markup:
        return None
    soup = BeautifulSoup(html.unescape(markup), "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(["p", "li", "h1", "h2", "h3", "h4", "div"]):
        tag.insert_before("\n")
        if tag.name == "li":
            tag.insert(0, "- ")
    lines = [" ".join(line.split()) for line in soup.get_text().splitlines()]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out or None


def work_model(value: str | None, location: str | None = None) -> str | None:
    v = (value or "").lower().replace("-", "").replace(" ", "")
    if v == "remote" or locations.is_remote(location):
        return "Remote"
    if v == "hybrid":
        return "Hybrid"
    if v in ("onsite", "inoffice"):
        return "On-site"
    return None


def when(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, int | float):  # Lever: milliseconds
        return datetime.fromtimestamp(value / 1000, UTC)
    try:
        out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=UTC)


def tidy(text: str | None) -> str | None:
    return " ".join(text.split()) if text else None
