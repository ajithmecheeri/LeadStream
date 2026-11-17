"""Oracle Recruiting Cloud career sites ("Candidate Experience"): the same public search the career site uses.

    GET https://<host>/hcmRestApi/resources/latest/recruitingCEJobRequisitions
        ?onlyData=true&finder=findReqs;siteNumber=<site>,selectedLocationsFacet=<India id>,limit=25,offset=n
    GET https://<host>/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails
        ?onlyData=true&expand=all&finder=ById;Id="<id>",siteNumber=<site>

India through the site's own location facet. Details only for jobs not read before. From the details only the job's
own text is kept: the recruiter's name and email there are never stored (decision 15). Checked against a real site
(JPMorgan Chase) on 2026-11-14.
"""

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from jobsearch.config import get_settings
from jobsearch.connectors.base import BoardNotFound, BoardResult, Posting, text_of, tidy, when, work_model
from jobsearch.locations import in_scope

PAGE = 25
MAX_UNFILTERED = 1000
DETAIL_CONCURRENCY = 3
COUNTRY_NAMES = {"IN": "india"}
_HOST = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.oraclecloud\.com$")
_SITE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


@dataclass(frozen=True)
class Board:
    host: str
    site: str

    @property
    def key(self) -> str:
        return f"{self.host}/{self.site}"

    @property
    def api(self) -> str:
        return f"https://{self.host}/hcmRestApi/resources/latest"

    @property
    def careers_url(self) -> str:
        return f"https://{self.host}/hcmUI/CandidateExperience/en/sites/{self.site}"

    def job_url(self, job_id: str) -> str:
        return f"{self.careers_url}/job/{job_id}"

    @classmethod
    def parse(cls, key: str) -> "Board":
        host, site = key.split("/")
        return cls(host, site)

    @classmethod
    def from_url(cls, url: str) -> "Board | None":
        """The site behind a career-site link: …oraclecloud.com/hcmUI/CandidateExperience/<lang>/sites/<site>/…"""
        t = url.strip()
        parts = urlsplit(t if "://" in t else "https://" + t)
        host = (parts.hostname or "").lower()
        m = re.search(r"/hcmUI/CandidateExperience/(?:[a-z]{2}(?:-[A-Z]{2})?/)?sites/([^/?#]+)", parts.path)
        if not _HOST.match(host) or not m or not _SITE.match(m.group(1)):
            return None
        return cls(host, m.group(1))


def _finder(board: Board, offset: int, facet: str | None, with_facets: bool) -> str:
    parts = [f"siteNumber={board.site}", f"limit={PAGE}", f"offset={offset}", "sortBy=POSTING_DATES_DESC"]
    if facet:
        parts.append(f"selectedLocationsFacet={facet}")
    if with_facets:
        parts.append("facetsList=LOCATIONS")
    return "findReqs;" + ",".join(parts)


def country_facet(item: dict, country: str = "IN") -> str | None:
    """The id of the country in the site's location facet ("India"), when it offers one."""
    name = COUNTRY_NAMES.get(country, country.lower())
    for loc in item.get("locationsFacet") or []:
        if (loc.get("Name") or "").strip().lower() == name and loc.get("Id"):
            return str(loc["Id"])
    return None


def listed(item: dict, board: Board, company: str) -> list[Posting]:
    """Jobs from a search page, without descriptions (needs_details), in scope only."""
    out = []
    for r in item.get("requisitionList") or []:
        if not r.get("Id") or not r.get("Title"):
            continue
        secondary = [s.get("Name") for s in r.get("secondaryLocations") or []]
        if not (
            r.get("PrimaryLocationCountry") == get_settings().country
            or in_scope(r.get("PrimaryLocation"), *secondary)
        ):
            continue
        places = [
            p for p in dict.fromkeys([tidy(r.get("PrimaryLocation")), *(tidy(s) for s in secondary)]) if p
        ]
        out.append(
            Posting(
                source="oracle",
                source_job_id=str(r["Id"]),
                title=" ".join(r["Title"].split()),
                company=company,
                location="; ".join(places) or None,
                url=board.job_url(str(r["Id"])),
                work_model=work_model(r.get("WorkplaceType"), r.get("PrimaryLocation")),
                posted_at=when(r.get("PostedDate")),
                requisition_id=str(r["Id"]),
                details={k: v for k, v in {"department": r.get("JobFamily")}.items() if v},
                needs_details=True,
            )
        )
    return out


def detailed(stub: Posting, data: dict) -> Posting:
    """The job with its description: the job's own text only (no recruiter, no company boilerplate)."""
    items = data.get("items") or []
    d = items[0] if items else {}
    parts = [
        text_of(d.get(k))
        for k in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")
    ]
    description = "\n\n".join(p for p in parts if p) or None
    details = dict(stub.details)
    if d.get("JobSchedule"):
        details["time_type"] = d["JobSchedule"]
    return Posting(
        source="oracle",
        source_job_id=stub.source_job_id,
        title=" ".join((d.get("Title") or stub.title).split()),
        company=stub.company,
        location=stub.location,
        url=stub.url,
        work_model=work_model(d.get("WorkplaceType"), d.get("PrimaryLocation")) or stub.work_model,
        description=description,
        details=details,
        posted_at=when(d.get("ExternalPostedStartDate")) or stub.posted_at,
        requisition_id=stub.requisition_id,
        needs_details=description is None,
    )


async def _search(
    http: httpx.AsyncClient, board: Board, offset: int, facet: str | None, with_facets=False
) -> dict:
    r = await http.get(
        f"{board.api}/recruitingCEJobRequisitions",
        params={
            "onlyData": "true",
            "expand": "requisitionList.secondaryLocations",
            "finder": _finder(board, offset, facet, with_facets),
        },
        headers={"Accept": "application/json"},
    )
    if r.status_code in (400, 404):
        raise BoardNotFound(board.key)
    r.raise_for_status()
    items = r.json().get("items") or []
    if not items:
        raise BoardNotFound(board.key)
    return items[0]


async def fetch(
    board: Board, company: str, http: httpx.AsyncClient, known: set[str], max_details: int | None = None
) -> BoardResult:
    if max_details is None:
        max_details = get_settings().workday_details_per_run
    first = await _search(http, board, 0, None, with_facets=True)
    total = int(first.get("TotalJobsCount") or 0)
    facet = country_facet(first, get_settings().country)
    page = await _search(http, board, 0, facet) if facet else first
    scope_total = int(page.get("TotalJobsCount") or 0) if facet else min(total, MAX_UNFILTERED)
    stubs = listed(page, board, company)
    offset = PAGE
    while offset < scope_total:
        page = await _search(http, board, offset, facet)
        if not page.get("requisitionList"):
            break
        stubs += listed(page, board, company)
        offset += PAGE
    stubs = list({s.source_job_id: s for s in stubs}.values())

    todo = [s for s in stubs if s.source_job_id not in known][:max_details]
    sem = asyncio.Semaphore(DETAIL_CONCURRENCY)

    async def read(stub: Posting) -> Posting:
        async with sem:
            try:
                finder = f'ById;Id="{stub.source_job_id}",siteNumber={board.site}'
                r = await http.get(
                    f"{board.api}/recruitingCEJobRequisitionDetails",
                    params={"onlyData": "true", "expand": "all", "finder": finder},
                    headers={"Accept": "application/json"},
                )
                r.raise_for_status()
                return detailed(stub, r.json())
            except (httpx.HTTPError, ValueError):
                return stub

    done = {p.source_job_id: p for p in await asyncio.gather(*(read(s) for s in todo))}
    postings = [done.get(s.source_job_id, s) for s in stubs]
    return BoardResult(postings, total, complete=bool(facet) or total <= MAX_UNFILTERED)
