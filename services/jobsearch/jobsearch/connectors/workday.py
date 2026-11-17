"""Workday career sites (decision 5 in docs/jobsearch-plan-discovery.md).

Reads the same public search a Workday careers page uses in the browser (no login, no key):

    POST https://<host>/wday/cxs/<tenant>/<site>/jobs   {"appliedFacets": {...}, "limit": 20, "offset": n}
    GET  https://<host>/wday/cxs/<tenant>/<site><externalPath>     one posting's details

Not officially documented, so it is read slowly and politely: India through the board's own country filter when
it has one, pages one after another, and details only for postings not read before (at most
`workday_details_per_run` a run, three at a time). Checked against a real board (NVIDIA) on 2026-11-14.
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx

from jobsearch.config import get_settings
from jobsearch.connectors.base import BoardNotFound, BoardResult, Posting, text_of, tidy, when, work_model
from jobsearch.locations import in_scope

PAGE = 20  # Workday refuses larger pages
MAX_UNFILTERED = 2000  # postings read from a board with no country filter
DETAIL_CONCURRENCY = 3
_LOCALE = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
_HOST = re.compile(r"^(?:[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com|wd\d+\.myworkdaysite\.com)$")
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
COUNTRY_NAMES = {"IN": "india"}


@dataclass(frozen=True)
class Board:
    """A Workday career site: host (acme.wd5.myworkdayjobs.com or wd3.myworkdaysite.com), tenant and site."""

    host: str
    tenant: str
    site: str

    @property
    def key(self) -> str:
        return f"{self.host}/{self.tenant}/{self.site}"

    @property
    def api(self) -> str:
        return f"https://{self.host}/wday/cxs/{self.tenant}/{self.site}"

    @property
    def careers_url(self) -> str:
        if self.host.endswith(".myworkdaysite.com"):
            return f"https://{self.host}/recruiting/{self.tenant}/{self.site}"
        return f"https://{self.host}/{self.site}"

    @classmethod
    def parse(cls, key: str) -> "Board":
        host, tenant, site = key.split("/")
        return cls(host, tenant, site)

    @classmethod
    def from_url(cls, url: str) -> "Board | None":
        """The board behind a Workday careers or job link, or None when it isn't one."""
        t = url.strip()
        if "://" not in t:
            t = "https://" + t
        parts = urlsplit(t)
        host = (parts.hostname or "").lower()
        if not _HOST.match(host):
            return None
        segs = [s for s in parts.path.split("/") if s]
        if segs[:2] == ["wday", "cxs"] and len(segs) >= 4:
            tenant, site = segs[2], segs[3]
        elif host.endswith(".myworkdaysite.com"):
            if segs and _LOCALE.match(segs[0]):
                segs = segs[1:]
            if len(segs) < 3 or segs[0] != "recruiting":
                return None
            tenant, site = segs[1], segs[2]
        else:
            if segs and _LOCALE.match(segs[0]):
                segs = segs[1:]
            if not segs or segs[0] in ("job", "details"):
                return None
            tenant, site = host.split(".")[0], segs[0]
        if not (_NAME.match(tenant) and _NAME.match(site)):
            return None
        return cls(host, tenant, site)


# --- Pure readers (tested with saved samples) --------------------------------------------------------------


def country_facet(facets: list[dict], country: str = "IN") -> dict[str, list[str]] | None:
    """The applied-facet filter for the country ({"locationHierarchy1": ["<id>"]}), when the board offers one."""
    name = COUNTRY_NAMES.get(country, country.lower())

    def walk(items: list[dict]) -> dict[str, list[str]] | None:
        for f in items:
            param = f.get("facetParameter")
            for v in f.get("values") or []:
                if "values" in v:  # a group of facets (locationMainGroup)
                    if found := walk([v]):
                        return found
                elif param and (v.get("descriptor") or "").strip().lower() == name and v.get("id"):
                    return {param: [v["id"]]}
        return None

    return walk(facets)


def posted(text: str | None, now: datetime) -> datetime | None:
    """ "Posted Today", "Posted Yesterday", "Posted 3 Days Ago"; "30+ Days Ago" is too vague to date."""
    t = (text or "").lower()
    if "+" in t:
        return None
    if "today" in t:
        days = 0
    elif "yesterday" in t:
        days = 1
    elif m := re.search(r"(\d+)\s+days?\s+ago", t):
        days = int(m.group(1))
    else:
        return None
    return (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)


def _list_location(p: dict) -> str | None:
    """ "India, Pune"; for "5 Locations" the first one, from the job's path (/job/India-Pune/...)."""
    text = p.get("locationsText") or ""
    if text and not re.match(r"^\d+\s+locations?$", text.strip(), re.I):
        return text
    segs = [s for s in (p.get("externalPath") or "").split("/") if s]
    if len(segs) >= 2 and segs[0] == "job":
        return segs[1].replace("-", ", ", 1).replace("-", " ")
    return None


def listed(page: dict, board: Board, company: str, now: datetime) -> list[Posting]:
    """Postings from a search page, without descriptions (needs_details=True), in scope only."""
    out = []
    for p in page.get("jobPostings") or []:
        path = p.get("externalPath")
        if not path or not p.get("title"):
            continue
        location = _list_location(p)
        if not in_scope(location, path.replace("-", " ")):
            continue
        bullets = [b for b in p.get("bulletFields") or [] if isinstance(b, str)]
        out.append(
            Posting(
                source="workday",
                source_job_id=path,
                title=" ".join(p["title"].split()),
                company=company,
                location=tidy(location),
                url=board.careers_url + path,
                work_model=work_model(None, location),
                posted_at=posted(p.get("postedOn"), now),
                requisition_id=next((b for b in bullets if re.search(r"\d", b)), None),
                needs_details=True,
            )
        )
    return out


def detailed(stub: Posting, data: dict) -> Posting:
    """The posting with its details read."""
    info = data.get("jobPostingInfo") or {}
    places = [info.get("location"), *(info.get("additionalLocations") or [])]
    location = "; ".join(p for p in dict.fromkeys(tidy(x) for x in places) if p) or stub.location
    details = {k: v for k, v in {"time_type": info.get("timeType")}.items() if v}
    return Posting(
        source="workday",
        source_job_id=stub.source_job_id,
        title=" ".join((info.get("title") or stub.title).split()),
        company=stub.company,
        location=location,
        url=info.get("externalUrl") or stub.url,
        work_model=work_model(info.get("remoteType"), info.get("location")) or stub.work_model,
        description=text_of(info.get("jobDescription")),
        details=details,
        posted_at=when(info.get("startDate")) or stub.posted_at,
        requisition_id=info.get("jobReqId") or stub.requisition_id,
        needs_details=False,
    )


# --- Fetching ----------------------------------------------------------------------------------------------


async def _search(http: httpx.AsyncClient, board: Board, offset: int, facets: dict | None) -> dict:
    r = await http.post(
        f"{board.api}/jobs",
        json={"appliedFacets": facets or {}, "limit": PAGE, "offset": offset, "searchText": ""},
        headers={"Accept": "application/json"},
    )
    if r.status_code in (404, 422):
        raise BoardNotFound(board.key)
    r.raise_for_status()
    return r.json()


async def fetch(
    board: Board, company: str, http: httpx.AsyncClient, known: set[str], max_details: int | None = None
) -> BoardResult:
    """The board's in-scope postings. `known` postings (already read) come back without details; up to
    `max_details` (default `workday_details_per_run`) new ones come back with them."""
    if max_details is None:
        max_details = get_settings().workday_details_per_run
    now = datetime.now(UTC)
    first = await _search(http, board, 0, None)
    total = int(first.get("total") or 0)
    if total == 0 and not first.get("jobPostings"):
        raise BoardNotFound(board.key)
    facets = country_facet(first.get("facets") or [], get_settings().country)
    page = await _search(http, board, 0, facets) if facets else first
    scope_total = int(page.get("total") or 0) if facets else min(total, MAX_UNFILTERED)
    stubs = listed(page, board, company, now)
    offset = PAGE
    while offset < scope_total:
        page = await _search(http, board, offset, facets)
        if not page.get("jobPostings"):
            break
        stubs += listed(page, board, company, now)
        offset += PAGE
    stubs = list({s.source_job_id: s for s in stubs}.values())

    todo = [s for s in stubs if s.source_job_id not in known][:max_details]
    sem = asyncio.Semaphore(DETAIL_CONCURRENCY)

    async def read(stub: Posting) -> Posting:
        async with sem:
            try:
                r = await http.get(f"{board.api}{stub.source_job_id}", headers={"Accept": "application/json"})
                r.raise_for_status()
                return detailed(stub, r.json())
            except (httpx.HTTPError, ValueError):
                return stub  # stays pending; tried again next run

    done = {p.source_job_id: p for p in await asyncio.gather(*(read(s) for s in todo))}
    postings = [done.get(s.source_job_id, s) for s in stubs]
    complete = bool(facets) or total <= MAX_UNFILTERED
    return BoardResult(postings, total, complete=complete)
