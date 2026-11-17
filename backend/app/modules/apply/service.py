"""The apply profile (milestone 14.1) and the Apply kit built from it (14.2).

The kit lists what an application form asks for, in Workday's order (My Information, My Experience, Application
Questions), from the account, the candidate profile, the apply profile and the answer bank. The browser extension
(14.3) reads the same facts. Nothing here writes to a job site: the user copies, or clicks Fill.
"""

import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.apply.models import ApplyProfile
from app.modules.apply.schemas import ApplyDraft, EducationEntry, KitDocument, KitField, KitSection, WorkEntry
from app.modules.candidate.models import CandidateProfile
from app.modules.documents.models import CoverLetter, Resume
from app.modules.documents.reader import read
from app.modules.matching.models import JobMatch
from app.modules.profiles.models import SearchProfile
from app.modules.readiness.models import Answer
from app.modules.readiness.questions import STANDARD
from app.modules.users.models import User

_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_NOW = ("present", "current", "now", "till date", "today")
_SCHOOL = re.compile(
    r"universit|institut|college|school|academy|\biit\b|\biim\b|\bnit\b|\bbits\b|\bisb\b", re.I
)
_DEGREE = re.compile(
    r"\b(b\.?\s?tech|b\.?\s?e\b|bachelor|b\.?\s?sc|b\.?\s?com|b\.?\s?a\b|bca|m\.?\s?tech|m\.?\s?e\b|master|m\.?\s?sc|"
    r"mba|pgdm|pgp|mca|ph\.?\s?d|doctor|diploma|executive programme|executive program)",
    re.I,
)
_YEAR = re.compile(r"\b(19[5-9]\d|20\d\d)\b")


def month(text: str | None) -> str | None:
    """'Jan 2019' → '2019-01'; '2019' → '2019-01'; 'Present' → None."""
    t = (text or "").strip().lower()
    y = _YEAR.search(t)
    if not y:
        return None
    m = next((i + 1 for i, name in enumerate(_MONTHS) if t.startswith(name)), 1)
    return f"{y.group(0)}-{m:02d}"


@dataclass
class _Line:
    school: str | None
    degree: str | None
    rest: list[str]  # other parts: the field of study on a degree line, often a city on a school line
    years: list[int]


def _line(text: str) -> _Line:
    years = [int(y) for y in _YEAR.findall(text)]
    parts = [
        p.strip(" .") for p in re.split(r"\s*[|,;–—]\s*|\s+-\s+", _YEAR.sub("", text)) if p.strip(" .()")
    ]
    school = next((p for p in parts if _SCHOOL.search(p)), None)
    degree = next((p for p in parts if _DEGREE.search(p) and p != school), None)
    return _Line(school, degree, [p for p in parts if p not in (school, degree)], years)


def education(lines: list[str]) -> list[EducationEntry]:
    """Education entries from a resume's education lines. A degree line and a school line next to each other
    ("B.Tech, Computer Science 2000 – 2004" / "Example Institute of Technology, Kochi") are one entry. An entry
    needs a school; a degree with no school named is left for the user to add."""
    parsed = [x for x in (_line(t) for t in lines) if x.school or x.degree]
    out: list[EducationEntry] = []
    i = 0
    while i < len(parsed):
        a = parsed[i]
        b = parsed[i + 1] if i + 1 < len(parsed) else None
        pair = b is not None and bool(a.degree) != bool(b.degree) and bool(a.school) != bool(b.school)
        deg, sch = ((a, b) if a.degree else (b, a)) if pair and b else (a, a)
        i += 2 if pair else 1
        if not sch.school:
            continue
        years = sorted(deg.years + (sch.years if sch is not deg else []))
        out.append(
            EducationEntry(
                school=sch.school[:200],
                degree=deg.degree[:200] if deg.degree else None,
                field=deg.rest[0][:200] if deg.degree and deg.rest else None,
                start_year=years[0] if len(years) > 1 else None,
                end_year=years[-1] if years else None,
            )
        )
    return out[:10]


def draft(text: str) -> ApplyDraft:
    """What a resume says that the apply profile holds: phone, city, work history (most recent first) and
    education. Rules only; the user reviews it before saving."""
    facts = read(text)
    work = []
    for r in facts.roles[:30]:
        current = (r.end or "").strip().lower() in _NOW
        work.append(
            WorkEntry(
                title=r.title[:200],
                company=(r.company or None) and r.company[:200],
                start=month(r.start),
                end=None if current else month(r.end),
                current=current,
                description=r.description,
            )
        )
    city = (facts.location or "").split(",")[0].strip() or None
    return ApplyDraft(phone=facts.phone, city=city, work_history=work, education=education(facts.education))


@dataclass
class Facts:
    """Everything the kit and the extension fill from, loaded once."""

    user: User
    candidate: CandidateProfile | None
    profile: ApplyProfile | None
    answers: list[Answer]
    skills: list[str] = field(default_factory=list)  # the primary resume's match profile: its own and added


async def load(db: AsyncSession, user_id: UUID) -> Facts:
    user = await db.get(User, user_id)
    assert user is not None
    answers = list(
        await db.scalars(select(Answer).where(Answer.search_profile_id.is_(None)).order_by(Answer.created_at))
    )
    cand = await db.get(CandidateProfile, user_id)
    # Skills for a form's Skills box: the primary resume's match profile (2026-11-13), else the old profile list.
    match_profile = await db.scalar(
        select(SearchProfile)
        .join(Resume, Resume.id == SearchProfile.resume_id)
        .order_by(Resume.is_primary.desc(), Resume.created_at)
        .limit(1)
    )
    skills = (
        [*match_profile.resume_skills, *match_profile.skills]
        if match_profile
        else list(cand.skills if cand else [])
    )
    return Facts(user, cand, await db.get(ApplyProfile, user_id), answers, skills)


def _field(key: str, label: str, value: object) -> KitField | None:
    text = "" if value is None else str(value).strip()
    return KitField(key=key, label=label, value=text) if text else None


def _month_label(value: str | None) -> str | None:
    if not value:
        return None
    y, m = value.split("-")
    return f"{_MONTHS[int(m) - 1].title()} {y}"


def answers(f: Facts) -> list[KitField]:
    """Screening answers: the answer bank first, then what the candidate profile says."""
    out: list[KitField] = []
    by_key = {a.key: a for a in f.answers}
    for s in STANDARD:
        a = by_key.pop(s.key, None)
        value = a.answer if a else (s.from_profile(f.candidate) if f.candidate else None)
        if item := _field(f"answer:{s.key}", s.question, value):
            out.append(item)
    out += [x for a in by_key.values() if (x := _field(f"answer:{a.key}", a.question, a.answer))]
    return out


def sections(f: Facts) -> tuple[list[KitSection], list[str]]:
    u, c, p = f.user, f.candidate, f.profile
    info = [
        _field("first_name", "First name", u.first_name),
        _field("last_name", "Last name", u.last_name),
        _field("email", "Email", u.email),
        _field("phone", "Phone", p and p.phone),
        _field("address_line1", "Address line 1", p and p.address_line1),
        _field("address_line2", "Address line 2", p and p.address_line2),
        _field("city", "City", (p and p.city) or (c and c.current_location)),
        _field("state", "State", p and p.state),
        _field("postal_code", "Postal code", p and p.postal_code),
        _field("country", "Country", p and p.country),
        _field("linkedin", "LinkedIn", c and c.linkedin_url),
        *[_field(f"website.{i}", "Website", w) for i, w in enumerate(p.websites if p else [])],
    ]
    experience: list[KitField | None] = []
    for i, w in enumerate(p.work_history if p else []):
        experience += [
            _field(f"work.{i}.title", f"Job title ({i + 1})", w.get("title")),
            _field(f"work.{i}.company", "Company", w.get("company")),
            _field(f"work.{i}.location", "Location", w.get("location")),
            _field(f"work.{i}.from", "From", _month_label(w.get("start"))),
            _field(
                f"work.{i}.to",
                "To",
                "I currently work here" if w.get("current") else _month_label(w.get("end")),
            ),
            _field(f"work.{i}.description", "Role description", w.get("description")),
        ]
    for i, e in enumerate(p.education if p else []):
        experience += [
            _field(f"education.{i}.school", f"School or university ({i + 1})", e.get("school")),
            _field(f"education.{i}.degree", "Degree", e.get("degree")),
            _field(f"education.{i}.field", "Field of study", e.get("field")),
            _field(f"education.{i}.from", "From (year)", e.get("start_year")),
            _field(f"education.{i}.to", "To (year)", e.get("end_year")),
        ]
    langs = ", ".join(
        f"{lang['language']} ({lang['proficiency']})" if lang.get("proficiency") else lang["language"]
        for lang in (p.languages if p else [])
    )
    experience += [
        _field("languages", "Languages", langs),
        _field("skills", "Skills", ", ".join(f.skills) or None),
    ]
    out = [
        KitSection(title="My information", fields=[x for x in info if x]),
        KitSection(title="My experience", fields=[x for x in experience if x]),
        KitSection(title="Application questions", fields=answers(f)),
    ]
    missing = [
        label
        for label, ok in (
            ("Phone", p and p.phone),
            ("Address", p and p.address_line1 and p.postal_code),
            ("Work history", p and p.work_history),
            ("Education", p and p.education),
        )
        if not ok
    ]
    return [s for s in out if s.fields], missing


async def documents(db: AsyncSession, user_job_id: UUID | None) -> list[KitDocument]:
    """The suggested resume and cover letter for the job (its match), else the primary resume."""
    match = await db.get(JobMatch, user_job_id) if user_job_id else None
    resume = await db.get(Resume, match.best_resume_id) if match and match.best_resume_id else None
    if resume is None:
        resume = await db.scalar(
            select(Resume).order_by(Resume.is_primary.desc(), Resume.created_at).limit(1)
        )
    letter = await db.get(CoverLetter, match.cover_letter_id) if match and match.cover_letter_id else None
    docs = [KitDocument(id=resume.id, label=resume.label, kind="resume")] if resume else []
    if letter:
        docs.append(KitDocument(id=letter.id, label=letter.label, kind="cover_letter"))
    return docs
