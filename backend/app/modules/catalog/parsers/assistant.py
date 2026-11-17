"""Job lists an AI assistant writes on a schedule (user, 2026-11-08: a ChatGPT task that searches employer career
pages and mails the results through the user's own Gmail).

The email comes from the user's own address, so it is read only when that address is listed on Mail setup
(registry.parse_email), and its jobs go into the catalog unverified like any hand forward. The assistant
writes plain text and its layout changes from run to run, so this parser reads numbered entries with labelled
lines and tolerates the variations seen so far:

    1) HEAD OF PRODUCT – AGENTIC ENGINEERING            4) Walmart Global Tech — Senior Director, Technical
    Employer: SAP                                       Program Management (R-2611361)
    Location / work mode: Bangalore; hybrid             Location: Bengaluru | On-site
    Posted: about 3 days ago                            Posted: … says "posted yesterday"; another indexed
    Role summary: Own product vision and …              copy says 23 days ago, so the posting-date record conflicts.
    Application:                                        Scope: Lead a team of TPMs …
    https://jobs.sap.com/en/jobs/744000159544088/…      Listing:
                                                        https://walmart.wd504.myworkdayjobs.com/…

An entry needs a title and an employer or a link. The role summary is the assistant's summary, not the
employer's description, so it goes in the details (scored as text) and the job still asks for the full
description before it can be a Strong match.

Posting dates: every date the "Posted" line gives is read and the oldest becomes `posted_at`. Dates that disagree
by a week or more (or wording like "conflicts", "discrepancy"), and an application deadline, are kept in
`details["posting"]` (a dict, so the job page doesn't list it) for the "May have expired" check (jobs/expiry.py).
"""

import hashlib
import re
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from app.modules.catalog.parsers.base import JobCard, ParseResult, clean, html_body, text_body
from app.modules.catalog.parsers.normalize import experience as years
from app.modules.catalog.parsers.normalize import split_location

_ENTRY = re.compile(r"^\s*(?:#{1,4}\s*)?(\d{1,2})[.)]\s+(\S.*)$")
_LABEL = re.compile(r"^\s*(?:[-*•]\s*)?\**([A-Za-z][A-Za-z /&()-]{1,40}?)\**\s*:\s*(.*)$")
_URL = re.compile(r"https?://\S+")
_LABELS = {
    "title": "title",
    "role": "title",
    "job title": "title",
    "employer": "company",
    "company": "company",
    "organisation": "company",
    "organization": "company",
    "location": "location",
    "location / work mode": "location",
    "location/work mode": "location",
    "location/work arrangement": "location",
    "work mode": "work_mode",
    "work arrangement": "work_mode",
    "source/date": "posted",
    "date/source": "posted",
    "apply/listing": "link",
    "listing/apply": "link",
    "official role details": "official_page",  # a second link (the listing's details page): kept apart
    "official application": "link",  # 2026-11-11 evening: the three jobs had come in without a link
    "official application link": "link",
    "official apply link": "link",
    "official link": "link",
    "official listing": "link",
    "application link": "link",
    "job link": "link",
    "employer application": "link",
    "employer link": "link",
    "note": "note",
    "posted": "posted",
    "date posted": "posted",
    "posting start date": "posted",
    "posting date": "posted",
    "source/posted": "posted",
    "source/age": "posted",
    "age": "posted",
    "application deadline": "deadline",
    "deadline": "deadline",
    "apply by": "deadline",
    "urgency": "deadline",
    "experience": "experience",
    "role summary": "summary",
    "summary": "summary",
    "scope": "summary",
    "description": "summary",
    "mandatory skill": "skills",
    "mandatory skills": "skills",
    "key skills": "skills",
    "source": "found_on",
    "application": "link",
    "apply": "link",
    "apply link": "link",
    "apply/view": "link",
    "view/apply": "link",
    "application route": "link",
    "listing": "link",
    "listing/application route": "link",
    "link": "link",
    "url": "link",
    "job id": "reference",
    "reference": "reference",
    "requisition": "reference",
    "requisition id": "reference",
    "salary": "salary",
    "compensation": "salary",
    "indicative compensation": "salary",
    "indicative compensation shown": "salary",
}
# Labels the assistant may pair with another word next time ("Location/work arrangement", "Source/date",
# "Apply/listing", 2026-11-11): read by their first word.
_PAIRED = {
    "location": "location",
    "source": "posted",
    "apply": "link",
    "application": "link",
    "listing": "link",
}
# A known label anywhere in an entry's text (checked against _LABELS); "Location / work mode" and
# "Location/work mode" are the same label.
_INLINE_LABEL = re.compile(
    r"(?:^|(?<=\s))[-*•]?\s*\**("
    + "|".join(sorted((re.escape(k).replace("/", r"\s*/\s*") for k in _LABELS), key=len, reverse=True))
    + r"|(?:"
    + "|".join(_PAIRED)
    + r")\s*/\s*[a-z]+(?: [a-z]+)?"
    + r")\**\s*:(?!//)",
    re.I,
)
_BOLD = re.compile(r"(\*{1,2})([^*]+?)\1", re.S)  # "*HARMAN India — Executive Director, …*" over two lines
# Fields kept as the job's public details, under the names the job page shows.
_DETAILS = (
    ("summary", "summary"),
    ("experience", "experience asked"),
    ("skills", "mandatory skills"),
    ("posted", "posted"),
    ("deadline", "apply by"),
    ("found_on", "found on"),
    ("reference", "reference"),
    ("note", "note"),
)
# A heading line that runs on to the next: it ends mid-phrase.
_CUT_OFF = re.compile(r"(?:[,&/(–—-]|\b(?:and|of|for|in|the|to|at|with|or|—))\s*$", re.I)
# "Company — Title" (an em dash with spaces; en dashes are used inside titles).
_COMPANY_TITLE = re.compile(r"^(.+?)\s+—\s+(.+)$")
# A requisition at the end of a title: "(R1004319)", "(Job ID 6108)", ", requisition R50034191".
_TITLE_REF = re.compile(
    r"\s*(?:,\s*requisition\s+([A-Z0-9][\w-]*)|\(\s*(?:job id|req(?:uisition)?(?: id)?)?\s*:?\s*"
    r"([A-Z]{0,3}-?\d[\w-]*)\s*\))\s*$",
    re.I,
)
# Section headings like "PUBLIC JOB-BOARD / RECRUITER LISTINGS — DIRECT EMPLOYER ROUTE NOT VERIFIED".
_THIRD_PARTY = re.compile(r"not verified|third[- ]party|recruiter|job[- ]board", re.I)
_MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()
_DATE = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})\b")
_DATE_NO_YEAR = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3})[a-z]*\b(?!\.?,?\s+\d{4})")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_AGO = re.compile(r"\b(\d{1,3}|a|an|one)\s*\+?\s*(day|week|month)s?\b", re.I)
_YESTERDAY = re.compile(r"\byesterday\b", re.I)
_TODAY = re.compile(r"\btoday\b|\bjust now\b|\bhours? ago\b", re.I)
_DOUBT = re.compile(r"conflict|discrepan|inconsisten|mismatch|unclear", re.I)
_ALERT_DATE = re.compile(r"^\s*(?:Alert|Search) date:\s*(.+)$", re.I | re.M)
_RANGE = re.compile(r"\b(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*(?:years|yrs)\b", re.I)
_AT_LEAST = re.compile(r"\b(\d{1,2})\s*\+?\s*(?:years|yrs)\b", re.I)
_MODELS = {
    "remote": "Remote",
    "hybrid": "Hybrid",
    "on-site": "On-site",
    "onsite": "On-site",
    "in office": "On-site",
    "in-office": "On-site",
    "work from office": "On-site",
    "office-based": "On-site",
    "office working": "On-site",
    "office based": "On-site",
}
_MODEL = re.compile(r"\b(" + "|".join(re.escape(k) for k in _MODELS) + r")\b", re.I)
_ASIDE = re.compile(
    r"\s*\((?!remote|hybrid|on-site)[^)]*\)\s*$", re.I
)  # "Bangalore (listing also mentions…)"
_PREFIX = re.compile(r"^\s*((re|fwd?|fw)\s*:\s*)+", re.I)
_TRACKING = re.compile(r"^(utm_\w+|source|src|ref|refid|trackingid|gh_src|lever-source|sa|usg|ust)$", re.I)
# Words an all-capitals title keeps in capitals, and the small words it lowercases.
_ACRONYMS = {
    **{
        w: w.upper()
        for w in (
            "ai ml vp avp svp evp gm dgm agm cto cio cfo ceo coo cpo it hr qa ui ux pmo sre sap apac emea us uk "
            "r&d b2b b2c aws gcp erp crm iot llm bfsi gcc"
        ).split()
    },
    "genai": "GenAI",
    "devops": "DevOps",
    "mlops": "MLOps",
    "saas": "SaaS",
}
_SMALL = {"of", "and", "for", "the", "to", "in", "at", "a", "an", "on", "with", "or", "&"}
# A week or more between two "posted" dates means the listings disagree (an old job re-posted or still indexed).
CONFLICT = timedelta(days=7)


def _title(text: str) -> str:
    """'HEAD OF PRODUCT – AGENTIC ENGINEERING' → 'Head of Product – Agentic Engineering'; mixed case is kept."""
    text = clean(text).strip("*_ ").rstrip(":")
    if any(c.islower() for c in text):
        return text
    out = []
    for i, word in enumerate(text.split(" ")):
        low = word.lower()
        bare = low.strip(",.()/")
        if bare in _ACRONYMS:
            out.append(low.replace(bare, _ACRONYMS[bare]))
        elif i and low in _SMALL:
            out.append(low)
        else:
            out.append("-".join(p[:1].upper() + p[1:] for p in low.split("-")))
    return " ".join(out)


def _link(text: str) -> str | None:
    """The first link, out of Gmail's google.com/url?q= wrapper, without tracking parameters."""
    m = _URL.search(text)
    if not m:
        return None
    url = m.group(0).rstrip(").,;>]")
    parts = urlsplit(url)
    if parts.netloc.endswith("google.com") and parts.path == "/url":
        url = (parse_qs(parts.query).get("q") or [url])[0]
        parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING.match(k)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _day(year: int, month: str, day: str) -> datetime | None:
    if month.lower() not in _MONTHS:
        return None
    try:
        return datetime(year, _MONTHS.index(month.lower()) + 1, int(day), tzinfo=UTC)
    except ValueError:
        return None


def dates(text: str, today: datetime) -> list[datetime]:
    """Every date a "Posted" line gives: "04 Nov 2026", "5 Nov", "2026-11-04", "yesterday", "23 days ago",
    "3 weeks ago", "14+ days"."""
    found: list[datetime | None] = [_day(int(y), mon, d) for d, mon, y in _DATE.findall(text)]
    found += [_day(today.year, mon, d) for d, mon in _DATE_NO_YEAR.findall(text)]
    found += [datetime(int(y), int(m), int(d), tzinfo=UTC) for y, m, d in _ISO_DATE.findall(text)]
    for n, unit in _AGO.findall(text):
        count = 1 if n.lower() in ("a", "an", "one") else int(n)
        found.append(today - timedelta(days=count * {"day": 1, "week": 7, "month": 30}[unit.lower()]))
    if _YESTERDAY.search(text):
        found.append(today - timedelta(days=1))
    if _TODAY.search(text):
        found.append(today)
    # A day-month without a year that would fall after the alert is from last year.
    return sorted(d if d <= today + timedelta(days=1) else d.replace(year=d.year - 1) for d in found if d)


def _experience(text: str) -> str | None:
    if m := _RANGE.search(text):
        return years(m[1], m[2])
    if m := _AT_LEAST.search(text):
        return f"{m[1]}+ years"
    return None


def _fields(section: str, text: str) -> dict[str, str]:
    """One entry's text as {field: value}. A label starts a line or, capitalised, runs on in the middle of one
    ("… (age discrepancy). Location/work mode: Bengaluru; hybrid. Experience: 20+ years."). The heading is a
    bold "*…*" if the entry starts with one, otherwise the text before the first label."""
    fields = {"_heading": "", "_section": section}
    labels = [
        m
        for m in _INLINE_LABEL.finditer(text)
        if (m.start() == 0 or text[m.start() - 1] == "\n" or m[1][0].isupper()) and _key(m[1])
    ]
    if bold := _BOLD.match(text):
        fields["_heading"] = bold[2]
        labels = [m for m in labels if m.start() >= bold.end()]
    else:
        # The heading is the entry's first line and the wrapped rest of a title: lines that read like one
        # ("Development, DevCMO Tech"), or any line after one cut off mid-phrase ("… Director,"). From the first
        # sentence on, the lines before the first label are a note (2026-11-13: "LinkedIn is now showing the role
        # as newly listed … not a second vacancy" had become part of the title).
        lines = (text[: labels[0].start()] if labels else text).split("\n")
        heading = lines.pop(0)
        while lines and (_CUT_OFF.search(heading) or _title_like(lines[0])):
            heading = f"{heading} {lines.pop(0)}"
        fields["_heading"] = heading
        if note := clean(" ".join(lines)):
            fields["note"] = note
    for i, m in enumerate(labels):
        key = _key(m[1])
        value = clean(text[m.end() : labels[i + 1].start() if i + 1 < len(labels) else len(text)])
        fields[key] = clean(f"{fields[key]} {value}") if key in fields else value
    fields["_heading"] = clean(fields["_heading"])
    return fields


_CONNECTORS = frozenset("and of for in the to at & – — - / , with".split())


def _title_like(line: str) -> bool:
    """Words of a title, not a sentence: mostly capitalised, apart from connectors ("and", "of", "–")."""
    words = [s for w in line.split() if w.lower() not in _CONNECTORS and (s := w.lstrip("([\"'“‘"))]
    return bool(words) and sum(w[0].isupper() or w[0].isdigit() for w in words) >= 0.75 * len(words)


def _is_prose(value: str) -> bool:
    """A "Role:" or "Title:" value that describes the job instead of naming it: long, or full sentences."""
    return len(value) > 120 or len(value.split()) > 16 or bool(re.search(r"[a-z]{3}\.\s+[A-Z]", value))


def _key(label: str) -> str | None:
    label = re.sub(r"\s*/\s*", "/", clean(label)).lower()
    if label in _LABELS:
        return _LABELS[label]
    first, slash, _ = label.partition("/")
    return _PAIRED.get(first) if slash else None


def _entries(text: str) -> list[dict[str, str]]:
    """Numbered entries as {field: value}, with "_heading" and "_section" (the capitalised heading above the
    entry, if any). An entry's text runs on over wrapped lines until a blank line or the next entry; after a
    blank line only a line that starts with a label carries it on."""
    blocks: list[tuple[str, list[str]]] = []
    section = ""
    open_ = False
    for raw in text.splitlines():
        line = raw.lstrip("> ").rstrip()
        if m := _ENTRY.match(line):
            blocks.append((section, [m[2].strip()]))
            open_ = True
            continue
        if not line.strip():
            open_ = False
            continue
        if not open_ and line.isupper() and len(line.split()) >= 3 and ":" not in line:
            section = clean(line)
            continue
        label = _LABEL.match(line)
        if blocks and (open_ or (label and _key(label[1]) and not _URL.match(line.strip()))):
            blocks[-1][1].append(line.strip())
            open_ = True
    return [_fields(section, "\n".join(lines)) for section, lines in blocks]


class AssistantAlert:
    """A job list from an AI assistant (ChatGPT and the like), mailed from the user's own address."""

    name = "ai_assistant_alert"
    version = 7

    def _text(self, msg: EmailMessage) -> str:
        text = text_body(msg)
        if not text.strip() and (soup := html_body(msg)):
            text = soup.get_text("\n")
        return text

    def matches(self, msg: EmailMessage) -> bool:
        return any(
            f.get("company") or f.get("link") or _COMPANY_TITLE.match(f["_heading"])
            for f in _entries(self._text(msg))
        )

    def parse(self, msg: EmailMessage) -> ParseResult:
        text = self._text(msg)
        try:
            sent = parsedate_to_datetime(str(msg["Date"])).astimezone(UTC)
        except (TypeError, ValueError):
            sent = datetime.now(UTC)
        midnight = sent.replace(hour=0, minute=0, second=0, microsecond=0)
        alert_day = _ALERT_DATE.search(text)
        today = next(iter(dates(alert_day[1], midnight)), midnight) if alert_day else midnight
        cards: list[JobCard] = []
        warnings: list[str] = []
        for f in _entries(text):
            if _is_prose(f.get("title", "")):  # "Role: Leads the global … function" (2026-11-11): a summary
                prose = f.pop("title")
                f["summary"] = clean(f"{prose} {f['summary']}") if f.get("summary") else prose
            heading, company = clean(f.get("title") or f["_heading"]), f.get("company")
            if not company and (split := _COMPANY_TITLE.match(heading)):
                company, heading = split[1], split[2]
            if ref := _TITLE_REF.search(heading):
                heading = heading[: ref.start()]
                f.setdefault("reference", ref[1] or ref[2])
            title = _title(heading)
            # Under a label not known yet, the link runs on into another field: the first link anywhere in the
            # entry then, so a new wording never leaves a job without its Apply button.
            link = next(
                (u for k in ("link", "_heading", *f, "official_page") if (u := _link(f.get(k, "")))), None
            )
            if not title or not (company or link):
                continue
            where, *rest = re.split(r"\s*[;|]\s*", f.get("location", ""))
            where = _ASIDE.sub("", clean(where)).rstrip(" .")
            location, model = split_location(where) if where else (None, None)
            if not model and (inline := _MODEL.search(where)) and inline.start():  # "Bengaluru, hybrid"
                rest, location = [inline[1], *rest], where[: inline.start()].rstrip(" ,/")
            said = _MODEL.search(" ".join([*rest, f.get("work_mode", "")]))
            # "Public job trackers conflict between remote and on-site": unknown, not the first one named.
            if said and _DOUBT.search(f.get("work_mode", "")):
                said = None
            details: dict = {label: f[k] for k, label in _DETAILS if f.get(k)}
            if _THIRD_PARTY.search(f["_section"]):
                details["employer page"] = "Not found by the assistant: a job-board or recruiter listing"
            posted = dates(f.get("posted", ""), today)
            closes = dates(f.get("deadline", ""), today)
            posting = {
                "dates": [d.date().isoformat() for d in posted],
                "conflict": bool(
                    (len(posted) > 1 and posted[-1] - posted[0] >= CONFLICT)
                    or _DOUBT.search(f.get("posted", ""))
                ),
                "closes_on": closes[0].date().isoformat() if closes else None,
            }
            if posting["conflict"] or posting["closes_on"]:
                details["posting"] = posting
            key = link or f"{title}|{company or ''}|{location or ''}"
            cards.append(
                JobCard(
                    source="ai_assistant",
                    source_job_id=hashlib.sha256(key.lower().encode()).hexdigest()[:20],
                    title=title,
                    company=company or None,
                    location=location,
                    lead="alert",
                    canonical_url=link,
                    apply_url=link,
                    work_model=model or (_MODELS[said[1].lower()] if said else None),
                    # Its first sentence: notes the assistant adds after it run on into the value.
                    salary=re.split(r"(?<=[.;])\s", f["salary"])[0].rstrip(".;") if f.get("salary") else None,
                    experience=_experience(f.get("experience", "")),
                    details=details,
                    posted_at=posted[0] if posted else None,  # the oldest: an old job may have been re-posted
                )
            )
        if not cards:
            warnings.append("no jobs found in the assistant's email")
        subject = _PREFIX.sub("", str(msg.get("Subject", ""))).strip()
        return ParseResult(
            f"{self.name}@{self.version}", cards, alert_name=subject or None, warnings=warnings
        )
