"""Adzuna's job-search API, India (api.adzuna.com/v1/api/jobs/in/search). Needs ADZUNA_APP_ID and ADZUNA_APP_KEY
(free at developer.adzuna.com). Moved from the main app; now searched per search area, not per user.

Adzuna gathers listings from many job sites. Only the fields its API returns are used, and the listing page is
never fetched (rule 2 in docs/jobsearch-plan-discovery.md). Its descriptions are snippets.
"""

import httpx

from jobsearch.config import get_settings
from jobsearch.connectors.base import Posting, text_of, when

SEARCH = "https://api.adzuna.com/v1/api/jobs/in/search/1"
PER_QUERY = 50
MAX_DAYS_OLD = 7


def configured() -> bool:
    s = get_settings()
    return bool(s.adzuna_app_id and s.adzuna_app_key)


def postings_from_adzuna(data: dict) -> list[Posting]:
    out = []
    for r in data.get("results") or []:
        title = text_of(r.get("title")) or ""
        if not title or not r.get("id"):
            continue
        lo, hi = r.get("salary_min"), r.get("salary_max")
        salary = None
        if lo or hi:
            salary = (
                "₹" + "–".join(f"{int(v):,}" for v in dict.fromkeys(v for v in (lo, hi) if v)) + " / year"
            )
            if r.get("salary_is_predicted") in ("1", 1, True):
                salary += " (Adzuna estimate)"
        out.append(
            Posting(
                source="adzuna",
                source_job_id=str(r["id"]),
                title=" ".join(title.split()),
                company=((r.get("company") or {}).get("display_name") or "").strip() or None,
                location=((r.get("location") or {}).get("display_name") or "").strip() or None,
                url=r.get("redirect_url"),
                salary=salary,
                description=text_of(r.get("description")),
                details={"category": c} if (c := (r.get("category") or {}).get("label")) else {},
                posted_at=when(r.get("created")),
            )
        )
    return out


async def search(role: str, location: str, http: httpx.AsyncClient) -> list[Posting]:
    s = get_settings()
    params = {
        "app_id": s.adzuna_app_id,
        "app_key": s.adzuna_app_key,
        "what": role,
        "results_per_page": PER_QUERY,
        "max_days_old": MAX_DAYS_OLD,
        "sort_by": "date",
        "content-type": "application/json",
    }
    if location and location.lower() not in ("remote", "anywhere", "india"):
        params["where"] = location
    r = await http.get(SEARCH, params=params)
    r.raise_for_status()
    return postings_from_adzuna(r.json())
