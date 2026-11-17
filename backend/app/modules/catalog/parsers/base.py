"""What every alert parser produces, and the small helpers they share."""

from dataclasses import dataclass, field
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Literal, Protocol

from bs4 import BeautifulSoup

Source = Literal[
    "linkedin",
    "naukri",
    "naukri_rdx",
    "foundit",  # only jobs the user adds by hand (jobs/found.py); never read from the site
    "greenhouse",
    "lever",
    "ashby",
    "smartrecruiters",
    "workday",
    "oracle",
    "eightfold",
    "careers_page",
    "adzuna",
    "ai_assistant",
]
# Sources that are a company's own careers site (read by the Job Search Service).
COMPANY_SITES = frozenset(
    {"greenhouse", "lever", "ashby", "smartrecruiters", "workday", "oracle", "eightfold", "careers_page"}
)
Lead = Literal["alert", "recommendation", "recruiter_invite", "company_feed", "job_board"]


@dataclass(frozen=True)
class JobCard:
    """One job as an alert email shows it. Public fields go to the shared catalog; `apply_url` is private."""

    source: Source
    source_job_id: str
    title: str
    company: str | None
    location: str | None
    lead: Lead
    canonical_url: str | None = None  # public job page, query string removed
    apply_url: str | None = None  # may carry the recipient's login token: store per user, never share
    work_model: str | None = None  # "Remote" | "Hybrid" | "On-site", as in search profiles
    salary: str | None = None
    experience: str | None = None  # "14-20 years"
    company_truncated: bool = False  # Naukri cuts long names: "Crescendo Global Le..."
    outside_preference: bool = False  # Naukri's "Jobs outside your preference" section
    skills: tuple[str, ...] = ()
    description: str | None = None  # full description, when the email carries it
    details: dict[str, str] = field(default_factory=dict)  # labelled facts about the job (public)
    posted_at: datetime | None = None  # when the company posted it (feeds and APIs say; alert emails don't)
    # Lines about the recipient, not the job ("2 connections", "Easy Apply"): stored per user, never shared.
    card_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParseResult:
    parser: str  # "linkedin_digest@1"
    cards: list[JobCard]
    alert_name: str | None = None
    warnings: list[str] = field(default_factory=list)
    # Cards the email says the user applied to (card index → the day), e.g. Naukri's "You applied for 1 job".
    # About the recipient: never stored in the shared catalog.
    applied: dict[int, date] = field(default_factory=dict)


class Parser(Protocol):
    name: str
    version: int

    def matches(self, msg: EmailMessage) -> bool: ...

    def parse(self, msg: EmailMessage) -> ParseResult: ...


def sender(msg: EmailMessage) -> str:
    """The From address, lowercased. parseaddr copes with Naukri's `name…==@naukri.com` local parts."""
    return parseaddr(str(msg.get("From", "")))[1].lower()


def sender_domain(msg: EmailMessage) -> str:
    return sender(msg).rpartition("@")[2]


def html_body(msg: EmailMessage) -> BeautifulSoup | None:
    part = msg.get_body(("html",))
    return BeautifulSoup(part.get_content(), "html.parser") if part else None


def text_body(msg: EmailMessage) -> str:
    part = msg.get_body(("plain",))
    return part.get_content() if part else ""


def clean(text: str | None) -> str:
    """Collapse whitespace, including the zero-width and no-break spaces that mailers pad with."""
    if not text:
        return ""
    return " ".join(text.replace("‌", " ").replace(" ", " ").split())
