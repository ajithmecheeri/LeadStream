"""A company's own careers site, read through what it publishes for search engines (step 2, decisions 12–14):

  1. robots.txt: every page read must be allowed for us (search pages usually aren't, so they're never used);
  2. the sitemap(s) robots.txt names (or /sitemap.xml): the job pages' addresses;
  3. each job page's schema.org JobPosting (JSON-LD, or microdata on older templates such as SuccessFactors'
     Career Site Builder): the same data Google Jobs reads.

Polite: at most `careers_pages_per_run` new pages a run, two at a time; pages whose address names India or an
Indian city first; a page found outside India is remembered (the caller passes it back in `skip`). Job portals are
refused (rule 1). A site without a sitemap is read from the links on its careers page only, and then nothing is
closed from it (decision 16). Checked against Arm (Radancy) and SAP's careers sites on 2026-11-14.
"""

import asyncio
import gzip
import json
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from jobsearch.config import get_settings
from jobsearch.connectors.base import USER_AGENT, BoardNotFound, BoardResult, Posting, text_of, tidy, when
from jobsearch.locations import CITY_ALIASES, in_scope

CONCURRENCY = 2
MAX_SITEMAPS = 25
MAX_JOB_URLS = 20_000
COUNTRY_NAMES = {"IN": ("in", "ind", "india")}

# Job portals and aggregators: never read as a careers site (non-negotiable rule 1).
PORTALS = (
    "linkedin.com",
    "naukri.com",
    "indeed.com",
    "indeed.co.in",
    "foundit.in",
    "monsterindia.com",
    "monster.com",
    "glassdoor.com",
    "glassdoor.co.in",
    "shine.com",
    "timesjobs.com",
    "iimjobs.com",
    "hirist.tech",
    "hirist.com",
    "instahyre.com",
    "cutshort.io",
    "wellfound.com",
    "angel.co",
    "apna.co",
    "internshala.com",
    "freshersworld.com",
    "ziprecruiter.com",
    "simplyhired.com",
    "careerbuilder.com",
    "dice.com",
    "jooble.org",
    "careerjet.co.in",
    "adzuna.in",
    "talent.com",
    "google.com",
    "workindia.in",
    "quikr.com",
    "olx.in",
)
_JOB_PATH = re.compile(
    r"/(?:jobs?|careers?/jobs?|positions?|openings?|vacanc(?:y|ies)|requisitions?|job-?details?|jobdetail)/",
    re.I,
)
_ID = re.compile(r"(?<![0-9])[0-9]{5,}(?![0-9])")
_LANG = re.compile(r"/(?:[a-z]{2})(?:[-_][a-z]{2})?/", re.I)
_INDIA_WORDS = sorted({a for names in CITY_ALIASES for a in names} | {"india"}, key=len, reverse=True)
_INDIA_HINT = re.compile(
    r"(?<![a-z])(" + "|".join(re.escape(w).replace(r"\ ", "[-_ ]") for w in _INDIA_WORDS) + r")(?![a-z])"
)


@dataclass(frozen=True)
class Site:
    """A careers site: host plus an optional path ("careers.arm.com", "www.acme.com/careers")."""

    host: str
    path: str = ""

    @property
    def key(self) -> str:
        return self.host + self.path

    @property
    def url(self) -> str:
        return f"https://{self.host}{self.path or '/'}"

    @classmethod
    def parse(cls, key: str) -> "Site":
        host, _, path = key.partition("/")
        return cls(host.lower(), f"/{path}".rstrip("/") if path else "")

    @classmethod
    def from_url(cls, url: str) -> "Site | None":
        t = url.strip()
        parts = urlsplit(t if "://" in t else "https://" + t)
        host = (parts.hostname or "").lower()
        if not re.match(r"^([a-z0-9-]+\.)+[a-z]{2,}$", host) or is_portal(host):
            return None
        path = re.sub(r"/+$", "", parts.path)
        # A job page's link stands for its whole site.
        if _JOB_PATH.search(path + "/"):
            path = ""
        return cls(host, path if re.match(r"^[A-Za-z0-9/._-]{0,120}$", path) else "")


def is_portal(host: str) -> bool:
    host = host.lower()
    return any(host == p or host.endswith("." + p) for p in PORTALS)


# --- Reading what the site publishes ------------------------------------------------------------------------


def job_id(url: str) -> str:
    """A job page's id: the longest number in its address, else its path. One id for a job published in several
    languages (/en/jobs/123/…, /de/jobs/123/…)."""
    path = urlsplit(url).path
    ids = _ID.findall(path)
    return max(ids, key=len) if ids else _LANG.sub("/", path.rstrip("/") + "/").rstrip("/").lower()


def base_domain(host: str) -> str:
    """The registrable part of a host: careers.arm.com → arm.com, jobs.acme.co.in → acme.co.in."""
    labels = host.lower().split(".")
    if (
        len(labels) >= 3
        and len(labels[-1]) == 2
        and labels[-2] in ("co", "com", "org", "net", "ac", "gov", "edu")
    ):
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def same_site(url: str, host: str) -> bool:
    return base_domain(urlsplit(url).hostname or "") == base_domain(host)


def is_job_url(url: str, host: str) -> bool:
    path = urlsplit(url).path
    return (
        same_site(url, host)
        and bool(_JOB_PATH.search(path))
        and (bool(_ID.search(path)) or path.count("/") >= 3)
    )


def india_hint(url: str) -> bool:
    return bool(_INDIA_HINT.search(urlsplit(url).path.lower()))


def sitemap_urls(xml: str) -> tuple[list[str], list[str]]:
    """(child sitemaps, page addresses) in a sitemap or sitemap index."""
    locs = [
        re.sub(r"\s+", "", m).replace("&amp;", "&") for m in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml, re.S)
    ]
    if re.search(r"<sitemapindex[\s>]", xml):
        return locs, []
    return [], locs


def pick_urls(urls: list[str], host: str) -> list[str]:
    """Job pages, one per job (English or language-free address preferred)."""
    best: dict[str, str] = {}
    for u in urls:
        if not is_job_url(u, host):
            continue
        k = job_id(u)
        cur = best.get(k)
        if cur is None or ("/en/" in u and "/en/" not in cur) or (len(u) < len(cur) and "/en/" not in cur):
            best[k] = u
    return list(best.values())


def _first(value):
    return value[0] if isinstance(value, list) and value else value


def _job_postings(data) -> list[dict]:
    """JobPosting objects in a JSON-LD value (a dict, a list, or a @graph)."""
    if isinstance(data, list):
        return [p for d in data for p in _job_postings(d)]
    if not isinstance(data, dict):
        return []
    kind = data.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    if "JobPosting" in kinds:
        return [data]
    return _job_postings(data.get("@graph") or [])


def _address(place) -> tuple[str | None, str | None]:
    """(location text, country) of a schema.org Place."""
    place = _first(place) or {}
    addr = _first(place.get("address")) if isinstance(place, dict) else None
    if isinstance(addr, str):
        return tidy(addr), None
    if not isinstance(addr, dict):
        return None, None
    country = addr.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name")
    parts = [addr.get("addressLocality"), addr.get("addressRegion"), country]
    return ", ".join(dict.fromkeys(tidy(str(p)) for p in parts if p)) or None, (
        str(country) if country else None
    )


def from_json_ld(job: dict) -> dict:
    places = job.get("jobLocation")
    places = places if isinstance(places, list) else [places] if places else []
    located = [_address(p) for p in places]
    org = _first(job.get("hiringOrganization"))
    ident = _first(job.get("identifier"))
    remote = "TELECOMMUTE" in str(job.get("jobLocationType") or "").upper()
    return {
        "title": tidy(str(job.get("title") or job.get("name") or "")),
        "description": text_of(job.get("description")),
        "locations": [loc for loc, _ in located if loc],
        "countries": [c for _, c in located if c]
        + [
            str(_first(r).get("name"))
            for r in [job.get("applicantLocationRequirements")]
            if isinstance(_first(r), dict)
        ],
        "remote": remote,
        "posted": job.get("datePosted"),
        "company": org.get("name") if isinstance(org, dict) else (org if isinstance(org, str) else None),
        "requisition": str(ident.get("value")) if isinstance(ident, dict) and ident.get("value") else None,
        "url": job.get("url"),
    }


def from_microdata(soup: BeautifulSoup) -> dict | None:
    """A JobPosting marked up with itemprop attributes (older career-site templates)."""
    scope = soup.find(attrs={"itemtype": re.compile(r"schema\.org/JobPosting", re.I)})
    if scope is None:
        return None

    def prop(name: str, within=scope) -> str | None:
        el = within.find(attrs={"itemprop": name})
        if el is None:
            return None
        return (
            el.get("content")
            or el.get("datetime")
            or (str(el) if name == "description" else el.get_text(" "))
        )

    place = scope.find(attrs={"itemprop": "jobLocation"}) or scope
    parts = [prop(n, place) for n in ("addressLocality", "addressRegion", "addressCountry")]
    org = scope.find(attrs={"itemprop": "hiringOrganization"})
    return {
        "title": tidy(prop("title") or ""),
        "description": text_of(prop("description")),
        "locations": [", ".join(dict.fromkeys(tidy(p) for p in parts if p))] if any(parts) else [],
        "countries": [tidy(parts[2])] if parts[2] else [],
        "remote": "TELECOMMUTE" in (prop("jobLocationType") or "").upper(),
        "posted": prop("datePosted"),
        "company": tidy(prop("name", org)) if org else None,
        "requisition": tidy(prop("identifier")),
        "url": None,
    }


def read_page(html: str) -> dict | None:
    """The job a page describes, or None when it carries no JobPosting."""
    for block in re.findall(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", html, re.S | re.I):
        try:
            jobs = _job_postings(json.loads(block.strip()))
        except ValueError:
            continue
        if jobs:
            return from_json_ld(jobs[0])
    return from_microdata(BeautifulSoup(html, "html.parser"))


def in_country(job: dict, country: str = "IN") -> bool:
    names = COUNTRY_NAMES.get(country, (country.lower(),))
    if any(c.strip().lower() in names for c in job["countries"]):
        return True
    return in_scope(*job["locations"])


def posting(site: Site, url: str, job: dict, company: str) -> Posting:
    loc = "; ".join(dict.fromkeys(job["locations"])) or None
    return Posting(
        source="careers_page",
        source_job_id=job_id(url),
        title=job["title"],
        company=company or job["company"],
        location=loc,
        url=job["url"] if job["url"] and urlsplit(job["url"]).hostname else url,
        work_model="Remote" if job["remote"] else None,
        description=job["description"],
        posted_at=when(job["posted"]),
        requisition_id=job["requisition"],
    )


# --- Fetching ----------------------------------------------------------------------------------------------


async def _get(http: httpx.AsyncClient, url: str) -> httpx.Response:
    return await http.get(url, headers={"Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"})


async def robots(http: httpx.AsyncClient, site: Site) -> RobotFileParser:
    rp = RobotFileParser()
    try:
        r = await _get(http, f"https://{site.host}/robots.txt")
    except httpx.HTTPError:
        rp.parse([])
        return rp
    if r.status_code in (401, 403):
        rp.disallow_all = True
    elif r.status_code >= 400:
        rp.allow_all = True
    else:
        rp.parse(r.text.splitlines())
    return rp


def _text(r: httpx.Response) -> str:
    body = r.content
    if body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return body.decode(r.encoding or "utf-8", errors="replace")


async def job_urls(http: httpx.AsyncClient, site: Site, rp: RobotFileParser) -> tuple[list[str], bool]:
    """The site's job pages from its sitemaps, or from its careers page's links (second value: from a sitemap)."""
    todo = list(rp.site_maps() or []) or [f"https://{site.host}/sitemap.xml"]
    seen: set[str] = set()
    pages: list[str] = []
    while todo and len(seen) < MAX_SITEMAPS and len(pages) < MAX_JOB_URLS:
        sm = todo.pop(0)
        if sm in seen or not rp.can_fetch(USER_AGENT, sm):
            continue
        seen.add(sm)
        try:
            r = await _get(http, sm)
        except httpx.HTTPError:
            continue
        if r.status_code >= 400:
            continue
        children, locs = sitemap_urls(_text(r))
        ours = [c for c in children if same_site(c, site.host)]
        # Job sitemaps first: an index often lists pages, posts and jobs.
        todo += sorted(ours, key=lambda c: 0 if re.search(r"job|career|position", c, re.I) else 1)
        pages += locs
    found = pick_urls(pages, site.host)
    if found:
        return found, True
    # No sitemap with job pages: the links on the careers page itself.
    if not rp.can_fetch(USER_AGENT, site.url):
        return [], False
    r = await _get(http, site.url)
    if r.status_code == 404:
        raise BoardNotFound(site.key)
    r.raise_for_status()
    links = [urljoin(str(r.url), a) for a in re.findall(r"""href=["']([^"'#]+)["']""", r.text)]
    return pick_urls([urlunsplit(urlsplit(u)._replace(fragment="")) for u in links], site.host), False


async def fetch(
    site: Site,
    company: str,
    http: httpx.AsyncClient,
    known: set[str],
    skip: set[str] | None = None,
    max_pages: int | None = None,
) -> BoardResult:
    """The site's jobs in India. `known`: job ids already read (come back as stubs, so they stay open); `skip`:
    pages found outside India or without a job, not read again. Out-of-India pages read now come back in
    `out_of_scope`."""
    skip = skip or set()
    max_pages = get_settings().careers_pages_per_run if max_pages is None else max_pages
    rp = await robots(http, site)
    if not rp.can_fetch(USER_AGENT, site.url) and rp.disallow_all:
        raise BoardNotFound(site.key)
    urls, from_sitemap = await job_urls(http, site, rp)
    if not urls:
        raise BoardNotFound(site.key)
    by_id = {job_id(u): u for u in urls if rp.can_fetch(USER_AGENT, u)}  # only pages we may read count
    stubs = [
        Posting(
            source="careers_page",
            source_job_id=i,
            title="",
            company=company,
            location=None,
            url=u,
            needs_details=True,
        )
        for i, u in by_id.items()
        if i in known
    ]
    new = [u for i, u in by_id.items() if i not in known and i not in skip]
    new.sort(key=lambda u: 0 if india_hint(u) else 1)
    sem = asyncio.Semaphore(CONCURRENCY)
    out_of_scope: list[str] = []

    async def read(url: str) -> Posting | None:
        async with sem:
            try:
                r = await _get(http, url)
                if r.status_code >= 400:
                    return None
                job = read_page(_text(r))
            except (httpx.HTTPError, ValueError):
                return None
        if job is None or not job["title"] or not in_country(job, get_settings().country):
            out_of_scope.append(job_id(url))
            return None
        return posting(site, url, job, company)

    read_now = [p for p in await asyncio.gather(*(read(u) for u in new[:max_pages])) if p]
    return BoardResult(
        stubs + read_now, total=len(by_id), complete=from_sitemap, out_of_scope=tuple(out_of_scope)
    )
