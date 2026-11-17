"""Google Alerts RSS feeds (discovery plan decision 10): the feed link, its Atom content, and the jobs in it.

Only Google's feed is read. Each entry's link is Google's redirect (`https://www.google.com/url?…&url=<target>`);
the target is read for the portal's job id like a link the user adds by hand (jobs/found.py), and the job page is
never opened. Title, company and place come from the title Google shows ("Acme hiring VP Engineering in
Bengaluru, Karnataka, India | LinkedIn"), or else from the link; the snippet is kept as a labelled detail, not as
a description (it is a fragment).
"""

import html
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

from app.modules.catalog.parsers.base import JobCard, clean
from app.modules.catalog.parsers.normalize import split_location
from app.modules.jobs import found

_FEED = re.compile(r"^/alerts/feeds/(\d{5,30})/(\d{5,30})/?$")
_ATOM = "{http://www.w3.org/2005/Atom}"
MAX_BYTES = 2_000_000
MAX_ENTRIES = 100


class NotAFeed(ValueError):
    pass


def feed_url(raw: str) -> str:
    """The feed link in one spelling: https://www.google.com/alerts/feeds/<user>/<alert>."""
    parts = urlsplit(raw.strip())
    host = (parts.hostname or "").lower()
    m = _FEED.match(parts.path)
    if parts.scheme not in ("http", "https") or host not in ("www.google.com", "google.com") or not m:
        raise NotAFeed(
            "Paste the alert's RSS feed link: it starts with https://www.google.com/alerts/feeds/ "
            "(on Google Alerts, the orange RSS icon next to the alert)"
        )
    return f"https://www.google.com/alerts/feeds/{m.group(1)}/{m.group(2)}"


@dataclass(frozen=True)
class Entry:
    link: str  # the target of Google's redirect
    title: str
    snippet: str | None
    published: datetime | None


@dataclass(frozen=True)
class Feed:
    query: str | None  # the alert's search, from the feed title "Google Alert - <query>"
    entries: list[Entry]


def _text(value: str | None) -> str:
    """Google's HTML fragments (<b>VP</b> Engineering &amp; …) as plain text."""
    return clean(html.unescape(re.sub(r"<[^>]+>", "", value or "")))


def target(link: str) -> str:
    """The real link behind Google's redirect (or the link itself)."""
    parts = urlsplit(link)
    host = (parts.hostname or "").lower()
    if host in ("www.google.com", "google.com") and parts.path == "/url":
        q = parse_qs(parts.query)
        return (q.get("url") or q.get("q") or [link])[0]
    return link


def _date(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def parse(body: bytes) -> Feed:
    if len(body) > MAX_BYTES:
        raise NotAFeed("The feed is too large")
    if b"<!DOCTYPE" in body[:2000].upper() or b"<!ENTITY" in body.upper():
        raise NotAFeed("That isn't a Google Alerts feed")
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as e:
        raise NotAFeed("That isn't a Google Alerts feed") from e
    if root.tag != f"{_ATOM}feed":
        raise NotAFeed("That isn't a Google Alerts feed")
    title = _text(root.findtext(f"{_ATOM}title"))
    query = re.sub(r"^Google Alert\s*-\s*", "", title) or None
    entries = []
    for e in root.findall(f"{_ATOM}entry")[:MAX_ENTRIES]:
        link = e.find(f"{_ATOM}link")
        href = link.get("href") if link is not None else None
        if not href:
            continue
        entries.append(
            Entry(
                link=target(href),
                title=_text(e.findtext(f"{_ATOM}title")),
                snippet=_text(e.findtext(f"{_ATOM}content")) or None,
                published=_date(e.findtext(f"{_ATOM}published")),
            )
        )
    return Feed(query, entries)


# --- Entries as jobs ---------------------------------------------------------------------------------------

_SITE_SUFFIX = re.compile(
    r"\s*(?:[|\-–—:]\s*)?(?:LinkedIn(?:\.com)?|Naukri(?:\.com)?|foundit(?:\.in)?(?: \(formerly Monster\))?)\s*$",
    re.I,
)
_LINKEDIN_TITLE = re.compile(r"^(?P<company>.+?) hiring (?P<title>.+?)(?: in (?P<place>[^|]+?))?$")
_JOB_IN_AT = re.compile(
    r"^(?P<title>.+?) (?:Job|Jobs) (?:in|at) (?P<company>.+?)(?: (?:in|at) (?P<place>.+))?$"
)
_SMALL = {"of", "and", "the", "for", "in", "at", "to", "a", "an", "on", "with"}
_UPPER = {
    "vp",
    "cto",
    "cio",
    "ceo",
    "ai",
    "ml",
    "it",
    "qa",
    "hr",
    "ui",
    "ux",
    "sre",
    "avp",
    "svp",
    "evp",
    "gm",
}


def _title_case(words: list[str]) -> str:
    return " ".join(
        w.upper() if w in _UPPER else w if i and w in _SMALL else w.capitalize() for i, w in enumerate(words)
    )


def _from_linkedin_link(url: str) -> tuple[str, str] | None:
    """'…/jobs/view/head-of-engineering-at-acme-group-4490581539' → ('Head of Engineering', 'Acme Group')."""
    m = re.search(r"/jobs/view/([a-z0-9-]+?)-\d{6,}/?$", urlsplit(url).path, re.I)
    if not m:
        return None
    words = [w for w in m.group(1).lower().split("-") if w]
    at = len(words) - 1 - words[::-1].index("at") if "at" in words else -1
    if at <= 0 or at == len(words) - 1:
        return None
    return _title_case(words[:at]), _title_case(words[at + 1 :])


def facts(source: str, url: str, title: str) -> tuple[str | None, str | None, str | None]:
    """(job title, company, place) from Google's title for the page, else from the link."""
    text = _SITE_SUFFIX.sub("", title).strip(" -|")
    if source == "linkedin" and (m := _LINKEDIN_TITLE.match(text)):
        return clean(m["title"]), clean(m["company"]), clean(m["place"]) if m["place"] else None
    if m := _JOB_IN_AT.match(text):
        return clean(m["title"]), clean(m["company"]), clean(m["place"]) if m["place"] else None
    if source == "linkedin" and (guess := _from_linkedin_link(url)):
        return guess[0], guess[1], None
    parts = [p.strip() for p in re.split(r"\s+[|\-–—]\s+", text) if p.strip()]
    if not parts:
        return None, None, None
    return parts[0], (parts[1] if len(parts) > 1 else None), None


@dataclass
class Read:
    cards: list[JobCard]
    other_links: int  # entries that aren't LinkedIn, Naukri or Foundit job pages (skipped)


def cards(feed: Feed) -> Read:
    out: dict[tuple[str, str], JobCard] = {}
    other = 0
    for e in feed.entries:
        try:
            source, job_id, canonical = found.portal_job(e.link)
        except found.NotAJobLink:
            other += 1
            continue
        title, company, place = facts(source, e.link, e.title)
        if not title:
            other += 1
            continue
        location, model = split_location(place) if place else (None, None)
        details = {"Found by": "Google Alerts"}
        if e.snippet:
            details["Google snippet"] = e.snippet[:600]
        out.setdefault(
            (source, job_id),
            JobCard(
                source=source,  # type: ignore[arg-type]
                source_job_id=job_id,
                title=title[:300],
                company=company[:200] if company else None,
                location=location,
                work_model=model,
                lead="job_board",
                canonical_url=canonical,
                details=details,
            ),
        )
    return Read(list(out.values()), other)
