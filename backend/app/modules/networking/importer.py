"""Read LinkedIn's "Connections" export: a CSV, or the ZIP LinkedIn emails (which holds Connections.csv).

The CSV starts with a few lines of notes, then the header
`First Name,Last Name,URL,Email Address,Company,Position,Connected On`. Dates look like "15 Oct 2024".
Pure functions: no database, no network.
"""

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime

from app.modules.networking.companies import company_key

MAX_ROWS = 30_000
_HEADER = ("first name", "last name")


class ExportFileError(ValueError):
    """The file isn't a LinkedIn connections export."""


@dataclass
class Person:
    person_key: str
    first_name: str | None
    last_name: str | None
    profile_url: str | None
    email: str | None
    company: str | None
    position: str | None
    connected_on: date | None
    company_key: str | None


def _text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ExportFileError("The file isn't readable text")


def _csv_bytes(file_name: str, data: bytes) -> bytes:
    if not (file_name.lower().endswith(".zip") or data[:4] == b"PK\x03\x04"):
        return data
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = [n for n in z.namelist() if n.lower().rsplit("/", 1)[-1] == "connections.csv"]
            if not names:
                raise ExportFileError(
                    "The ZIP has no Connections.csv. Ask LinkedIn for the Connections data."
                )
            info = z.getinfo(names[0])
            if info.file_size > 20 * 1024 * 1024:
                raise ExportFileError("Connections.csv is too large")
            return z.read(info)
    except zipfile.BadZipFile as e:
        raise ExportFileError("The file isn't a valid ZIP") from e


def _clean(v: str | None) -> str | None:
    v = " ".join((v or "").split())
    return v or None


def _date(v: str | None) -> date | None:
    v = _clean(v)
    for fmt in ("%d %b %Y", "%d-%b-%y", "%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(v or "", fmt).date()
        except ValueError:
            continue
    return None


def _profile_url(v: str | None) -> str | None:
    v = _clean(v)
    if not v or "linkedin.com/" not in v.lower():
        return None
    return v.split("?", 1)[0].rstrip("/")


def read_connections(file_name: str, data: bytes, keep_email: bool = False) -> tuple[list[Person], int]:
    """The people in the export, and how many rows were skipped (no name). Emails are dropped unless
    `keep_email`: they are rarely there, and not needed to find a warm path."""
    lines = _text(_csv_bytes(file_name, data)).splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if all(h in ln.lower() for h in _HEADER) and "," in ln), None
    )
    if start is None:
        raise ExportFileError(
            "This doesn't look like LinkedIn's Connections export (no 'First Name, Last Name' header)"
        )
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    fields = {(f or "").strip().lower(): f for f in reader.fieldnames or []}

    def col(row: dict, name: str) -> str | None:
        key = fields.get(name)
        return row.get(key) if key else None

    people: dict[str, Person] = {}
    skipped = 0
    for row in reader:
        first, last = _clean(col(row, "first name")), _clean(col(row, "last name"))
        if not first and not last:
            skipped += 1
            continue
        url = _profile_url(col(row, "url"))
        company = _clean(col(row, "company"))
        key = (
            url.lower()
            if url
            else f"name:{(first or '').lower()} {(last or '').lower()}|{company_key(company) or ''}"
        )
        people[key] = Person(
            person_key=key,
            first_name=first,
            last_name=last,
            profile_url=url,
            email=_clean(col(row, "email address")) if keep_email else None,
            company=company,
            position=_clean(col(row, "position")),
            connected_on=_date(col(row, "connected on")),
            company_key=company_key(company),
        )
        if len(people) > MAX_ROWS:
            raise ExportFileError(f"The file has more than {MAX_ROWS:,} connections")
    return list(people.values()), skipped
