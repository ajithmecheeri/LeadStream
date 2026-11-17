"""Turning portal-specific wording into the catalog's values, and the dedupe fingerprint."""

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

# Search profiles use these three values (app/modules/profiles/schemas.py: WorkModel).
_WORK_MODELS = {
    "remote": "Remote",
    "hybrid": "Hybrid",
    "on-site": "On-site",
    "onsite": "On-site",
    "in office": "On-site",
    "work from office": "On-site",
}
_TRAILING_MODEL = re.compile(r"\s*\((remote|hybrid|on-site)\)\s*$", re.I)  # LinkedIn: "Bengaluru (Hybrid)"
_LEADING_MODEL = re.compile(r"^(remote|hybrid)\s*-\s*", re.I)  # Naukri: "Hybrid - Bengaluru"
_COMPANY_SUFFIX = re.compile(r"\b(private|pvt|limited|ltd|llp|inc|llc|corp|corporation|co)\b\.?", re.I)


def work_model(value: str | None) -> str | None:
    return _WORK_MODELS.get(value.strip().lower()) if value else None


def split_location(value: str) -> tuple[str | None, str | None]:
    """'Bengaluru East (Hybrid)' or 'Hybrid - Bengaluru' → ('Bengaluru East', 'Hybrid')."""
    for rx in (_TRAILING_MODEL, _LEADING_MODEL):
        m = rx.search(value)
        if m:
            return (value[: m.start()] + value[m.end() :]).strip() or None, work_model(m.group(1))
    return value.strip() or None, None


def experience(low: str | int, high: str | int) -> str:
    return f"{int(low)}-{int(high)} years"


def strip_query(url: str) -> str:
    """Drop the query string and fragment: alert links carry tracking and sign-in tokens."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, "", ""))


def _key(value: str | None) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split())


def fingerprint(company: str | None, title: str, location: str | None) -> str | None:
    """Same company + title + location → same job, across portals. None without a company to anchor it."""
    company_key = _key(_COMPANY_SUFFIX.sub(" ", company or ""))
    if not company_key:
        return None
    raw = "|".join((company_key, _key(title), _key(location)))
    return hashlib.sha256(raw.encode()).hexdigest()
