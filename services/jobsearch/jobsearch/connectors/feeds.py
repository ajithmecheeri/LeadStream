"""Company job boards with public APIs: Greenhouse, Lever, Ashby and SmartRecruiters.

Moved from the main app (backend/app/modules/sources/feeds.py, milestone 9) with the same rules: these APIs exist
so that companies' jobs can be shown on other sites; no login, no key. India jobs only. The `postings_from_*`
functions are pure (tested with saved samples); `fetch` does the HTTP.
"""

import asyncio

import httpx

from jobsearch.connectors.base import BoardNotFound, BoardResult, Posting, text_of, tidy, when, work_model
from jobsearch.locations import in_scope

SYSTEMS = ("greenhouse", "lever", "ashby", "smartrecruiters")
_SR_DETAILS = 100  # SmartRecruiters lists postings without descriptions: fetch at most this many


def _posting(source: str, job_id, title: str, company: str, location: str | None, url: str | None, **kw):
    return Posting(
        source=source,
        source_job_id=str(job_id),
        title=" ".join(title.split()),
        company=company,
        location=tidy(location),
        url=url,
        **kw,
    )


# --- Greenhouse: boards-api.greenhouse.io/v1/boards/<board>/jobs?content=true ----------------------------


def postings_from_greenhouse(data: dict, company: str) -> BoardResult:
    jobs = data.get("jobs") or []
    out = []
    for j in jobs:
        location = (j.get("location") or {}).get("name")
        offices = [o.get("name") for o in j.get("offices") or []]
        if not in_scope(location, *offices):
            continue
        departments = [d["name"] for d in j.get("departments") or [] if d.get("name")]
        out.append(
            _posting(
                "greenhouse",
                j["id"],
                j["title"],
                company,
                location,
                j.get("absolute_url"),
                work_model=work_model(None, location),
                description=text_of(j.get("content")),
                details={"department": departments[0]} if departments else {},
                posted_at=when(j.get("first_published") or j.get("updated_at")),
                requisition_id=str(j["requisition_id"]) if j.get("requisition_id") else None,
            )
        )
    return BoardResult(out, len(jobs))


# --- Lever: api.lever.co/v0/postings/<board>?mode=json ---------------------------------------------------


def postings_from_lever(data: list, company: str) -> BoardResult:
    out = []
    for j in data:
        cat = j.get("categories") or {}
        locs = [cat.get("location"), *(cat.get("allLocations") or [])]
        if not in_scope(*locs, j.get("country")):
            continue
        parts = [j.get("descriptionPlain") or ""]
        for section in j.get("lists") or []:
            parts.append(f"{section.get('text', '')}\n{text_of(section.get('content')) or ''}")
        parts.append(j.get("additionalPlain") or "")
        description = "\n\n".join(p.strip() for p in parts if p and p.strip()) or None
        salary = j.get("salaryRange") or {}
        out.append(
            _posting(
                "lever",
                j["id"],
                j["text"],
                company,
                cat.get("location"),
                j.get("hostedUrl"),
                apply_url=j.get("applyUrl"),
                work_model=work_model(j.get("workplaceType"), cat.get("location")),
                description=description,
                salary=_range(
                    salary.get("min"), salary.get("max"), salary.get("currency"), salary.get("interval")
                ),
                details={
                    k: v
                    for k, v in {"department": cat.get("department"), "team": cat.get("team")}.items()
                    if v
                },
                posted_at=when(j.get("createdAt")),
            )
        )
    return BoardResult(out, len(data))


def _range(lo, hi, currency, interval) -> str | None:
    if not lo and not hi:
        return None
    nums = "–".join(f"{int(v):,}" for v in (lo, hi) if v)
    return " ".join(p for p in (currency, nums, (interval or "").replace("-", " ")) if p)


# --- Ashby: api.ashbyhq.com/posting-api/job-board/<board>?includeCompensation=true ------------------------


def postings_from_ashby(data: dict, company: str) -> BoardResult:
    jobs = data.get("jobs") or []
    out = []
    for j in jobs:
        if j.get("isListed") is False:
            continue
        secondary = [s.get("location") for s in j.get("secondaryLocations") or []]
        country = ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
        if not in_scope(j.get("location"), *secondary, country):
            continue
        comp = (j.get("compensation") or {}).get("compensationTierSummary")
        out.append(
            _posting(
                "ashby",
                j["id"],
                j["title"],
                company,
                j.get("location"),
                j.get("jobUrl"),
                apply_url=j.get("applyUrl"),
                work_model=work_model(j.get("workplaceType") or ("Remote" if j.get("isRemote") else None)),
                description=j.get("descriptionPlain") or text_of(j.get("descriptionHtml")),
                salary=comp or None,
                details={"department": j["department"]} if j.get("department") else {},
                posted_at=when(j.get("publishedAt")),
            )
        )
    return BoardResult(out, len(jobs))


# --- SmartRecruiters: api.smartrecruiters.com/v1/companies/<board>/postings?country=in -------------------


def postings_from_smartrecruiters(
    postings: list[dict], details: dict[str, dict], company: str, board: str
) -> BoardResult:
    """`postings` are India postings (the API filters by country, so `total` counts India only); `details`
    holds full postings by id."""
    out = []
    for p in postings:
        loc = p.get("location") or {}
        # "Chennai, , India": SmartRecruiters leaves empty parts in fullLocation.
        full = loc.get("fullLocation") or ", ".join(
            str(loc.get(k) or "") for k in ("city", "region", "country")
        )
        location = ", ".join(part.strip() for part in full.split(",") if part.strip())
        sections = ((details.get(p["id"]) or {}).get("jobAd") or {}).get("sections") or {}
        parts = [
            f"{s.get('title', '')}\n{text_of(s.get('text')) or ''}".strip()
            for key in ("jobDescription", "qualifications", "additionalInformation")
            if (s := sections.get(key)) and s.get("text")
        ]
        level = (p.get("experienceLevel") or {}).get("label")
        out.append(
            _posting(
                "smartrecruiters",
                p["id"],
                p["name"],
                company,
                location or "India",
                f"https://jobs.smartrecruiters.com/{board}/{p['id']}",
                work_model="Remote" if loc.get("remote") else ("Hybrid" if loc.get("hybrid") else None),
                description="\n\n".join(parts) or None,
                details={
                    k: v
                    for k, v in {"department": (p.get("function") or {}).get("label"), "level": level}.items()
                    if v
                },
                posted_at=when(p.get("releasedDate")),
                requisition_id=p.get("refNumber") or None,
            )
        )
    # Details are read for the first _SR_DETAILS only, so a longer board isn't "complete" for closing.
    return BoardResult(out, len(postings))


# --- Fetching --------------------------------------------------------------------------------------------


async def _json(http: httpx.AsyncClient, url: str, **params):
    r = await http.get(url, params=params or None)
    if r.status_code == 404:
        raise BoardNotFound(url)
    r.raise_for_status()
    return r.json()


async def fetch(system: str, board: str, company: str, http: httpx.AsyncClient) -> BoardResult:
    if system == "greenhouse":
        data = await _json(http, f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", content="true")
        return postings_from_greenhouse(data, company)
    if system == "lever":
        data = await _json(http, f"https://api.lever.co/v0/postings/{board}", mode="json")
        if not isinstance(data, list):
            raise BoardNotFound(board)
        return postings_from_lever(data, company)
    if system == "ashby":
        data = await _json(
            http, f"https://api.ashbyhq.com/posting-api/job-board/{board}", includeCompensation="true"
        )
        return postings_from_ashby(data, company)
    if system == "smartrecruiters":
        return await _smartrecruiters(http, board, company)
    raise ValueError(f"unknown hiring system {system}")


async def _smartrecruiters(http: httpx.AsyncClient, board: str, company: str) -> BoardResult:
    base = f"https://api.smartrecruiters.com/v1/companies/{board}/postings"
    postings: list[dict] = []
    found = 0
    while len(postings) < 300:
        page = await _json(http, base, country="in", limit=100, offset=len(postings))
        content = page.get("content") or []
        postings += content
        found = page.get("totalFound") or 0
        if len(content) < 100 or len(postings) >= found:
            break
    if not postings:
        raise BoardNotFound(board)
    sem = asyncio.Semaphore(4)

    async def detail(pid: str) -> tuple[str, dict]:
        async with sem:
            try:
                return pid, await _json(http, f"{base}/{pid}")
            except (httpx.HTTPError, BoardNotFound):
                return pid, {}

    details = dict(await asyncio.gather(*(detail(p["id"]) for p in postings[:_SR_DETAILS])))
    result = postings_from_smartrecruiters(postings, details, company, board)
    return BoardResult(result.postings, result.total, complete=len(postings) >= found)
