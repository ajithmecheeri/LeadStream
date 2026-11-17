"""The app's client for the Job Search Service's internal API (docs/jobsearch-plan-discovery.md, section 7).

Only aggregated, non-personal data goes out: employers and boards, search areas. `connect()` is the one place
that opens the connection, so tests replace it with a fake service.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import httpx

from app.core.config import get_settings


class Unavailable(Exception):
    """The service didn't answer, or answered with a server error."""


class Refused(Exception):
    """The service refused the request (4xx): `code` and `message` come from its error envelope."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class JobSearch:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    async def _call(self, method: str, path: str, **kw):
        try:
            r = await self.http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise Unavailable(f"{type(e).__name__}") from e
        if r.status_code >= 500:
            raise Unavailable(f"HTTP {r.status_code}")
        if r.status_code >= 400:
            err = (
                (r.json().get("error") or {})
                if r.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            raise Refused(r.status_code, err.get("code", "error"), err.get("message", r.text[:200]))
        return r.json() if r.content else None

    async def register(
        self,
        *,
        name: str | None = None,
        system: str | None = None,
        board: str | None = None,
        url: str | None = None,
        employer_id: UUID | None = None,
    ) -> dict:
        body = {k: v for k, v in {"name": name, "system": system, "board": board, "url": url}.items() if v}
        if employer_id:
            body["id"] = str(employer_id)
        return await self._call("POST", "/v1/employers", json=body)

    async def lookup(self, query: str) -> list[dict]:
        return await self._call("POST", "/v1/employers/lookup", json={"query": query})

    async def employers(self, ids: list[UUID]) -> list[dict]:
        if not ids:
            return []
        return await self._call("GET", "/v1/employers", params=[("ids", str(i)) for i in ids])

    async def listings(self, employer_id: UUID) -> dict:
        """The employer's open listings and its board's last run."""
        return await self._call("GET", f"/v1/employers/{employer_id}/listings")

    async def suggested(self) -> list[dict]:
        return await self._call("GET", "/v1/employers/suggested")

    async def check(self, employer_id: UUID) -> dict | None:
        """Check one employer now and wait for it; None when it was checked a few minutes ago."""
        try:
            return await self._call("POST", f"/v1/employers/{employer_id}/check", params={"wait": "true"})
        except Refused as e:
            if e.code == "checked_recently":
                return None
            raise

    async def events(self, after: int, limit: int = 500) -> dict:
        return await self._call("GET", "/v1/events", params={"after": after, "limit": limit})

    async def put_demand(self, areas: list[dict]) -> dict:
        return await self._call("PUT", "/v1/demand/search-areas", json={"areas": areas})

    async def sources(self) -> list[dict]:
        return await self._call("GET", "/v1/sources")


@asynccontextmanager
async def connect() -> AsyncIterator[JobSearch]:
    s = get_settings()
    async with httpx.AsyncClient(
        base_url=s.jobsearch_url,
        timeout=s.jobsearch_timeout_seconds,
        headers={"Authorization": f"Bearer {s.jobsearch_token}"},
    ) as http:
        yield JobSearch(http)
