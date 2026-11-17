"""Read a resume's facts by rules: contact details, headline, summary, roles, skills, domains, education.

This is the fallback for the `resume_extract` prompt, and the only reader until an Anthropic key is set.
It understands the common layout: name, headline and contact lines at the top, then sections under
capitalised headings, with roles written as "Title | Company<TAB>Mon YYYY – Present".
"""

import re
from datetime import date

from pydantic import BaseModel, Field

from app.modules.matching import taxonomy

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_WHEN = rf"(?:(?:{_MONTHS})[a-z]*\.?\s+)?(?:19|20)\d\d"
_RANGE = re.compile(rf"({_WHEN})\s*[–—-]+\s*({_WHEN}|present|current|now|till date|today)", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<![\d(])(\+?\(?\d[\d\s().-]{8,}\d)(?!\d)")
_LINKEDIN = re.compile(r"linkedin\.com/in/([\w-]+)", re.I)
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:years|yrs)", re.I)

SECTIONS = {
    "summary": [
        "professional summary",
        "summary",
        "profile",
        "about me",
        "executive summary",
        "career summary",
    ],
    "skills": [
        "core competencies",
        "competencies",
        "skills",
        "technical skills",
        "key skills",
        "areas of expertise",
        "expertise",
        "technology stack",
        "tools",
    ],
    "experience": [
        "professional experience",
        "experience",
        "work experience",
        "employment history",
        "career history",
    ],
    "education": ["education", "academic qualifications", "qualifications", "education and certifications"],
    "certifications": ["certifications", "certificates", "licenses and certifications"],
    "achievements": ["key achievements", "achievements", "awards"],
}
_HEADING = {name: key for key, names in SECTIONS.items() for name in names}
_ACRONYMS = {
    "vp",
    "svp",
    "evp",
    "avp",
    "cto",
    "ceo",
    "cio",
    "ai",
    "ml",
    "it",
    "hr",
    "qa",
    "pmo",
    "saas",
    "gm",
}


class Role(BaseModel):
    title: str
    company: str | None = None
    start: str | None = None
    end: str | None = None
    description: str | None = None  # the lines under the role line, up to the next role or section


class ResumeFacts(BaseModel):
    """What a resume says, in the candidate profile's terms. Every field may be empty."""

    name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    location: str | None = None
    headline: str | None = None
    summary: str | None = None
    years_experience: int | None = Field(None, ge=0, le=60)
    current_title: str | None = None
    roles: list[Role] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)


def read(text: str, today: date | None = None) -> ResumeFacts:
    today = today or date.today()
    lines = _lines(text)
    top, sections = _split_sections(lines)
    facts = ResumeFacts()

    joined = "\n".join(lines)
    if m := _EMAIL.search(joined):
        facts.email = m.group(0)
    if m := _LINKEDIN.search(joined):
        facts.linkedin_url = f"https://www.linkedin.com/in/{m.group(1)}"
    for ln in top:
        if (m := _PHONE.search(ln)) and not _RANGE.search(ln):
            facts.phone = " ".join(m.group(1).split())
            break

    facts.name, facts.headline, facts.location = _head(top)
    if summary := sections.get("summary"):
        facts.summary = " ".join(summary)[:4000]
    # Roles can follow sub-headings inside the experience section ("Key achievements:"), so every section
    # but education is searched for "Title | Company  Mon YYYY – Present" lines.
    facts.roles = [
        r for key, lns in sections.items() if key not in ("education", "certifications") for r in _roles(lns)
    ]
    current = [
        r for r in facts.roles if (r.end or "").lower() in ("present", "current", "now", "till date", "today")
    ]
    facts.current_title = (current or facts.roles or [Role(title="")])[0].title or None
    if not facts.headline and facts.current_title:
        facts.headline = facts.current_title
    facts.years_experience = _years(facts.summary or facts.headline or "", facts.roles, today)
    facts.skills = _skills(sections.get("skills", []))
    facts.domains = taxonomy.domains(joined)
    facts.education = [ln for ln in sections.get("education", []) if ln][:8]
    return facts


def _lines(text: str) -> list[str]:
    # Headings glued to the previous line by some exporters ("…ProductsEDUCATION").
    text = re.sub(r"([a-z)])(EDUCATION|EXPERIENCE|CERTIFICATIONS|SKILLS)\b", r"\1\n\2", text)
    return [ln.strip(" \t•▪·●◦-–*").strip() for ln in text.splitlines() if ln.strip()]


def _heading(line: str) -> str | None:
    key = re.sub(r"[^a-z& ]", "", line.lower()).strip()
    if len(line) > 45 or not key:
        return None
    if line.isupper() or line.endswith(":") or key in _HEADING:
        return _HEADING.get(key.rstrip(":"))
    return None


def _split_sections(lines: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    top: list[str] = []
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for ln in lines:
        key = _heading(ln)
        if key:
            current = sections.setdefault(key, [])
        elif current is None:
            top.append(ln)
        else:
            current.append(ln)
    return top, sections


def _title_case(s: str) -> str:
    if not s.isupper():
        return s
    words = []
    for w in s.split(" "):
        bare = re.sub(r"[^A-Za-z]", "", w).lower()
        words.append(w if bare in _ACRONYMS else w.capitalize())
    return " ".join(words)


def _head(top: list[str]) -> tuple[str | None, str | None, str | None]:
    """Name, headline and location from the lines above the first section."""
    name = headline = location = None
    for i, ln in enumerate(top[:8]):
        contact = _EMAIL.search(ln) or _LINKEDIN.search(ln) or _PHONE.search(ln)
        clean = re.sub(r"^[^\w]+", "", ln).strip()
        if i == 0 and not contact and 1 < len(clean.split()) <= 5 and not re.search(r"\d", clean):
            name = _title_case(clean)
            continue
        if headline is None and not contact and name and len(clean) <= 150 and not re.search(r"\d{3}", clean):
            if not taxonomy.cities(clean)[0]:
                headline = _title_case(clean)
                continue
        for part in re.split(r"[•|·▪]|\s{3,}", ln):
            part = re.sub(r"^[^\w]+", "", part).strip()
            if part and not (_EMAIL.search(part) or _LINKEDIN.search(part) or _PHONE.search(part)):
                if taxonomy.cities(part)[0] and location is None:
                    location = part
    return name, headline, location


def _roles(lines: list[str]) -> list[Role]:
    roles: list[Role] = []
    notes: list[str] = []  # the lines under the last role

    def close() -> None:
        if roles and notes:
            roles[-1].description = "\n".join(notes)[:4000]
        notes.clear()

    for ln in lines:
        m = _RANGE.search(ln)
        if not m:
            if roles and (line := re.sub(r"^[\s•▪●◦*·-]+", "", ln).strip()):
                notes.append(line)
            continue
        head = ln[: m.start()].strip(" \t|,")
        if len(head) > 120:  # a sentence that mentions dates, not a role line
            continue
        parts = [p.strip() for p in re.split(r"\s*[|▪]\s*|\t| {2,}", head) if p.strip()]
        if not parts:
            continue
        title = parts[0]
        company = parts[1] if len(parts) > 1 else None
        if company:
            company = re.split(r"\s+[—–-]\s+", company)[0].strip()
        close()
        roles.append(Role(title=title, company=company, start=m.group(1), end=m.group(2)))
    close()
    return roles


def _year(s: str | None) -> int | None:
    m = re.search(r"(19|20)\d\d", s or "")
    return int(m.group(0)) if m else None


def _years(text: str, roles: list[Role], today: date) -> int | None:
    if m := _YEARS.search(text):
        return int(m.group(1))
    starts = [y for y in (_year(r.start) for r in roles) if y]
    return today.year - min(starts) if starts else None


def _skills(lines: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for ln in lines:
        body = ln.split(":", 1)[1] if ":" in ln and len(ln.split(":", 1)[0]) < 40 else ln
        body = body.replace("(", ",").replace(")", "")
        for item in re.split(r",|;|\||/(?=\s)|\s{2,}", body):
            item = item.strip(" .")
            if not item or len(item) > 50 or len(item.split()) > 6 or item[0].isdigit():
                continue
            key = item.lower()
            if key not in seen:
                seen.add(key)
                out.append(item)
    return out[:80]
