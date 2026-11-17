"""Eightfold career sites: the public job search the career site itself uses (its robots.txt allows /api/apply).

    GET https://<host>/api/apply/v2/jobs?domain=<company domain>&location=India&start=n&num=10
    GET https://<host>/api/apply/v2/jobs/<id>?domain=<company domain>

The `domain` comes from the careers link (?domain=netflix.com) or, failing that, from the careers page. Details
only for jobs not read before. Checked against a real site (Netflix) on 2026-11-14.
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx

from jobsearch.config import get_settings
from jobsearch.connectors.base import BoardNotFound, BoardResult, Posting, text_of, tidy, work_model
from jobsearch.locations import in_scope

PAGE = 10
MAX_POSITIONS = 1000
DETAIL_CONCURRENCY = 3
COUNTRY_NAMES = {"IN": "India"}
_HOST = re.compile(r"^([a-z0-9-]+\.)+[a-z]{2,}$")
_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
_WORK = {"onsite": "On-site", "on-site": "On-site", "hybrid": "Hybrid", "remote": "Remote"}


@dataclass(frozen=True)
class Board:
    host: str  # explore.jobs.netflix.net, or <company>.eightfold.ai
    domain: str  # netflix.com; "" until read from the careers page

    @property
    def key(self) -> str:
        return f"{self.host}/{self.domain}"

    @property
    def careers_url(self) -> str:
        return f"https://{self.host}/careers" + (f"?domain={self.domain}" if self.domain else "")

    @classmethod
    def parse(cls, key: str) -> "Board":
        host, domain = key.split("/")
        return cls(host, domain)

    @classmethod
    def from_url(cls, url: str) -> "Board | None":
        """An Eightfold careers link: <x>.eightfold.ai/careers…, or any host's /careers/job/<id> or
        /careers?domain=… (Eightfold sites on a company's own host)."""
        t = url.strip()
        parts = urlsplit(t if "://" in t else "https://" + t)
        host = (parts.hostname or "").lower()
        domain = (parse_qs(parts.query).get("domain") or [""])[0].lower()
        eightfold_host = host.endswith(".eightfold.ai")
        looks_like = parts.path.startswith("/careers") and (domain or "/careers/job/" in parts.path)
        if not _HOST.match(host) or not (eightfold_host or looks_like):
            return None
        if domain and not _DOMAIN.match(domain):
            return None
        return cls(host, domain)


def listed(data: dict, company: str) -> list[Posting]:
    out = []
    for p in data.get("positions") or []:
        if not p.get("id") or not p.get("name"):
            continue
        places = [tidy(x) for x in (p.get("locations") or [p.get("location")]) if x]
        if not in_scope(*places):
            continue
        out.append(
            Posting(
                source="eightfold",
                source_job_id=str(p["id"]),
                title=" ".join(p["name"].split()),
                company=company,
                location="; ".join(dict.fromkeys(pl.replace(",", ", ") for pl in places)) or None,
                url=p.get("canonicalPositionUrl"),
                work_model=_WORK.get((p.get("work_location_option") or "").lower()),
                posted_at=datetime.fromtimestamp(p["t_create"], UTC) if p.get("t_create") else None,
                requisition_id=p.get("display_job_id") or p.get("ats_job_id"),
                details={k: v for k, v in {"department": p.get("department")}.items() if v},
                needs_details=True,
            )
        )
    return out


def detailed(stub: Posting, data: dict) -> Posting:
    description = text_of(data.get("job_description"))
    return Posting(
        source="eightfold",
        source_job_id=stub.source_job_id,
        title=" ".join((data.get("posting_name") or data.get("name") or stub.title).split()),
        company=stub.company,
        location=stub.location,
        url=data.get("canonicalPositionUrl") or stub.url,
        work_model=_WORK.get((data.get("work_location_option") or "").lower())
        or stub.work_model
        or work_model(None, stub.location),
        description=description,
        details=stub.details,
        posted_at=stub.posted_at,
        requisition_id=stub.requisition_id,
        needs_details=description is None,
    )


async def find_domain(board: Board, http: httpx.AsyncClient) -> Board:
    """The company domain the job search needs, read from the careers page when the link didn't carry it."""
    if board.domain:
        return board
    r = await http.get(f"https://{board.host}/careers")
    if r.status_code == 404:
        raise BoardNotFound(board.key)
    r.raise_for_status()
    m = re.search(r"""["']?domain["']?\s*[:=]\s*["']([a-z0-9-]+(?:\.[a-z0-9-]+)+)["']""", r.text)
    if not m:
        raise BoardNotFound(board.key)
    return Board(board.host, m.group(1))


async def fetch(
    board: Board, company: str, http: httpx.AsyncClient, known: set[str], max_details: int | None = None
) -> BoardResult:
    if max_details is None:
        max_details = get_settings().workday_details_per_run
    board = await find_domain(board, http)
    country = COUNTRY_NAMES.get(get_settings().country, get_settings().country)
    base = f"https://{board.host}/api/apply/v2/jobs"
    stubs: list[Posting] = []
    start, total = 0, None
    while start < MAX_POSITIONS:
        r = await http.get(
            base,
            params={"domain": board.domain, "location": country, "start": start, "num": PAGE},
            headers={"Accept": "application/json"},
        )
        if r.status_code in (403, 404):
            raise BoardNotFound(board.key)
        r.raise_for_status()
        data = r.json()
        total = int(data.get("count") or 0)
        positions = data.get("positions") or []
        stubs += listed(data, company)
        start += PAGE
        if not positions or start >= total:
            break
    stubs = list({s.source_job_id: s for s in stubs}.values())

    todo = [s for s in stubs if s.source_job_id not in known][:max_details]
    sem = asyncio.Semaphore(DETAIL_CONCURRENCY)

    async def read(stub: Posting) -> Posting:
        async with sem:
            try:
                r = await http.get(
                    f"{base}/{stub.source_job_id}",
                    params={"domain": board.domain},
                    headers={"Accept": "application/json"},
                )
                r.raise_for_status()
                return detailed(stub, r.json())
            except (httpx.HTTPError, ValueError):
                return stub

    done = {p.source_job_id: p for p in await asyncio.gather(*(read(s) for s in todo))}
    postings = [done.get(s.source_job_id, s) for s in stubs]
    return BoardResult(postings, total or 0, complete=(total or 0) <= MAX_POSITIONS)
