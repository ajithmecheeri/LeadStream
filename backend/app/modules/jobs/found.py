"""Jobs the user finds on Google (user, 2026-11-14: "route 1", free; paid search APIs are in the backlog).

BrewMyJob never reads job portals (CLAUDE.md, non-negotiable 1). Instead it offers ready-made Google searches for
the user's target roles and job locations, limited to LinkedIn, Naukri and Foundit job pages. The user runs them
in their own browser and adds the jobs they like by hand: the link, the title, company and place they see, and the
description if they paste it. The link is only read for the portal's job id (so an alert that later brings the
same job finds it); the page is never fetched.
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from app.modules.alerts.query import BadQuery, google_terms, names_place
from app.modules.catalog.parsers.base import JobCard, clean
from app.modules.catalog.parsers.normalize import split_location

# portal → (label, the part of the site that holds single job pages)
PORTALS: dict[str, tuple[str, str]] = {
    "linkedin": ("LinkedIn", "linkedin.com/jobs/view"),
    "naukri": ("Naukri", "naukri.com/job-listings"),
    "foundit": ("Foundit", "foundit.in/job"),
}
MAX_ROLES, MAX_PLACES = 8, 4
_REMOTE = {"remote", "anywhere", "work from home", "wfh", "remote india"}
# Places the portals spell two ways.
OTHER_NAME = {
    "bengaluru": "Bangalore",
    "bangalore": "Bengaluru",
    "gurugram": "Gurgaon",
    "gurgaon": "Gurugram",
    "mumbai": "Bombay",
    "bombay": "Mumbai",
}


@dataclass(frozen=True)
class Search:
    role: str
    place: str | None
    queries: dict[str, str]  # portal → Google query


def place_key(place: str) -> str:
    """Bengaluru and Bangalore are one place: the same search covers both spellings."""
    low = place.lower()
    return min(low, OTHER_NAME.get(low, low).lower())


def unique(values: list[str], limit: int, key=str.lower) -> list[str]:
    seen: dict[str, str] = {}
    for v in values:
        v = clean(v)
        if v and key(v) not in seen:
            seen[key(v)] = v
    return list(seen.values())[:limit]


def place_term(place: str) -> str:
    low = place.lower()
    if low in _REMOTE:
        return "remote"
    # Every name quoted (user, 2026-11-15): '("Bengaluru" OR "Bangalore")', '"New Delhi"'.
    name = f'"{place}"'
    other = OTHER_NAME.get(low)
    return f'({name} OR "{other}")' if other else name


def role_terms(role: str) -> str:
    """The role in Google's syntax: one quoted phrase, or alternatives the user wrote with OR (alerts/query.py)."""
    try:
        return google_terms(role)
    except BadQuery:
        return f'"{role.replace(chr(34), "")}"'


def query(portal: str, role: str, place: str | None) -> str:
    q = f"site:{PORTALS[portal][1]} {role_terms(role)}"
    return f"{q} {place_term(place)}" if place else q


def searches(roles: list[str], places: list[str]) -> list[Search]:
    """One search per role and job location, each as a Google query per portal. The roles are the ones set on
    Find on Google, shared with Google Alerts (user, 2026-11-17); a role that names its city gets one search."""
    out = []
    cities = unique(places, MAX_PLACES, place_key)
    for role in unique(roles, MAX_ROLES):
        where = [None] if names_place(role, cities, OTHER_NAME) else (cities or [None])
        for place in where:
            out.append(Search(role, place, {p: query(p, role, place) for p in PORTALS}))
    return out


# --- Adding a job the user found ------------------------------------------------------------------------

_LINKEDIN_PATH = re.compile(r"^/(?:comm/)?jobs/view/(?:[^/]*?-)?(\d{6,})/?$")
_NAUKRI_PATH = re.compile(r"^/(?:jd/)?job-listings-[^/]*?-(\d{9,})/?$")
_FOUNDIT_PATH = re.compile(r"^/(?:job|seeker/job-details)/[^/]*?-(\d{5,})/?$")


class NotAJobLink(ValueError):
    pass


def _host_is(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def portal_job(url: str) -> tuple[str, str, str]:
    """(source, the portal's job id, canonical link) for a LinkedIn, Naukri or Foundit job page link."""
    parts = urlsplit(url.strip())
    host, path = (parts.hostname or "").lower(), parts.path
    if parts.scheme not in ("http", "https") or not host:
        raise NotAJobLink("Paste the job's full link, starting with https://")
    if _host_is(host, "linkedin.com"):
        m = _LINKEDIN_PATH.match(path)
        job_id = m.group(1) if m else (parse_qs(parts.query).get("currentJobId") or [""])[0]
        if job_id.isdigit():
            return "linkedin", job_id, f"https://www.linkedin.com/jobs/view/{job_id}/"
        raise NotAJobLink(
            "That LinkedIn link isn't a job page: open the job and copy its link (…/jobs/view/…)"
        )
    if _host_is(host, "naukri.com"):
        if m := _NAUKRI_PATH.match(path):
            return "naukri", m.group(1), f"https://www.naukri.com{path.rstrip('/')}"
        raise NotAJobLink(
            "That Naukri link isn't a job page: open the job and copy its link (…/job-listings-…)"
        )
    if _host_is(host, "foundit.in"):
        if m := _FOUNDIT_PATH.match(path):
            return "foundit", m.group(1), f"https://www.foundit.in{path.rstrip('/')}"
        raise NotAJobLink("That Foundit link isn't a job page: open the job and copy its link (…/job/…)")
    raise NotAJobLink(
        "Only LinkedIn, Naukri and Foundit job links can be added here. For a company's own careers site, "
        "follow the company on Job sources."
    )


def card(url: str, title: str, company: str, location: str | None) -> JobCard:
    source, job_id, canonical = portal_job(url)
    place, model = split_location(location) if location else (None, None)
    return JobCard(
        source=source,  # type: ignore[arg-type]
        source_job_id=job_id,
        title=clean(title),
        company=clean(company),
        location=place,
        work_model=model,
        lead="job_board",
        canonical_url=canonical,
    )
