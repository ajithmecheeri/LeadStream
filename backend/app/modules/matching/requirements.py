"""What a job description requires, section by section (user feedback 2026-11-16).

A description is read as headed sections. Bullets under a requirements heading ("Preferred candidate profile" is
Naukri's name for it, "Target profile", "Qualifications", "Requirements", "Must have", "Education"…) are
must-haves; bullets under "Preferred skills", "Nice to have", "Good to have"… are preferred only and never cost
points. Elsewhere a line that says it is a must ("must have", "mandatory", "required") is a must-have, and one that
says it is preferred ("preferred", "a plus") is preferred. Pure functions, no database.
"""

import re
from dataclasses import dataclass, field

MUST, PREFERRED, OTHER = "must", "preferred", "other"

# A heading is a short line, alone, maybe with a colon or ** around it. Checked in this order: "Preferred skills"
# is preferred, but "Preferred candidate profile" (Naukri) is the requirements.
_HEADINGS: list[tuple[str, re.Pattern[str]]] = [
    (
        PREFERRED,
        re.compile(
            r"(?:preferred|desired|desirable|additional|bonus)\s+(?:skills?|qualifications?|experience|keyskills)"
            r"|nice[\s-]to[\s-]haves?(?:\s+skills)?|good[\s-]to[\s-]haves?(?:\s+skills)?|bonus(?:\s+points)?"
            r"|(?:it'?s\s+)?a\s+plus|plus\s+points?|added\s+advantage|desirable"
        ),
    ),
    (
        MUST,
        re.compile(
            r"(?:preferred|desired|ideal|target(?:ed)?)?\s*candidate(?:'s)?\s+profile|target(?:ed)?\s+profile"
            r"|desired\s+profile|(?:required|basic|minimum|essential|key|mandatory)?\s*qualifications?(?:\s+required)?"
            r"|(?:job\s+|key\s+|minimum\s+)?requirements?|must[\s-]haves?(?:\s+skills)?|mandatory\s+skills"
            r"|required\s+skills|key\s+skills\s+required|skills\s+required|what\s+you(?:'ll)?\s+(?:need|bring)"
            r"|what\s+we(?:'re|\s+are)?\s+looking\s+for|who\s+you\s+are|eligibility(?:\s+criteria)?"
            r"|education(?:al)?(?:\s+qualifications?)?|(?:skills|experience)\s+(?:and|&)\s+(?:skills|experience)"
        ),
    ),
    (
        OTHER,
        re.compile(
            r"job\s+description|about\s+(?:the\s+)?(?:role|job|company|us|team)|role\s+(?:purpose|overview|summary)"
            r"|(?:key\s+)?responsibilities|what\s+you(?:'ll)?\s+do|overview|benefits|perks|why\s+join(?:\s+us)?"
            r"|leadership\s+(?:and|&)\s+personal\s+attributes|personal\s+attributes|success\s+indicators"
            r"|key\s+skills|the\s+role|your\s+role|position\s+summary"
        ),
    ),
]
# Naukri's footer facts ("Role: …", "Industry Type: …") end whatever section came before.
_FACT_LINE = re.compile(
    r"^(?:role|industry type|department|employment type|role category|location)\s*:", re.I
)
_BULLET = re.compile(r"^\s*(?:[-•●▪◦*·]|\d{1,2}[.)])\s*")
_JOINED = re.compile(r"(?<=[.;])\s+[-•●▪]\s+")  # two bullets pasted on one line
_SAYS_MUST = re.compile(
    r"\bmust(?:\s+have|\s+be)?\b|\bmandatory\b|\brequired\b|\bminimum\s+of\b|\bat\s+least\b"
)
_SAYS_PREFERRED = re.compile(
    r"\bpreferred\b|\bpreferably\b|nice[\s-]to[\s-]have|good[\s-]to[\s-]have|\b(?:is\s+)?a\s+plus\b|\badvantage\b"
    r"|\bdesirable\b|\bbonus\b"
)
_DEGREES = [  # (level, name, pattern): the highest degree a text names
    (3, "PhD", re.compile(r"\bph\.?\s?d\b|\bdoctorate\b|\bdoctoral\b", re.I)),
    (
        2,
        "Master's",
        re.compile(
            r"\bmaster(?:'?s)?\s+(?:degree|in|of)\b|\bmasters\b|\bm\.?\s?tech\b|\bmba\b|\bm\.?sc\b|\bmca\b|\bpost[\s-]?graduate\b",
            re.I,
        ),
    ),
    (
        1,
        "Bachelor's",
        re.compile(r"\bbachelor'?s?\b|\bb\.?\s?tech\b|\bb\.e\.|\bb\.?sc\b|\bbca\b|\bgraduate\b", re.I),
    ),
]
MAX_ITEM = 220  # characters kept of one requirement


@dataclass(frozen=True)
class Item:
    text: str  # as written, bullet removed
    kind: str  # must | preferred
    section: str | None  # the heading it sat under


@dataclass
class Requirements:
    must: list[Item] = field(default_factory=list)
    preferred: list[Item] = field(default_factory=list)

    @property
    def degree(self) -> tuple[int, str] | None:
        """The highest degree the must-haves ask for, e.g. (3, "PhD")."""
        found = [d for i in self.must if (d := degree_in(i.text))]
        return max(found) if found else None


def degree_in(text: str) -> tuple[int, str] | None:
    for level, name, pattern in _DEGREES:
        if pattern.search(text):
            return level, name
    return None


def _heading(line: str) -> str | None:
    s = line.strip().strip("*_#:").strip().rstrip(":").strip().lower()
    s = re.sub(r"\s+", " ", s.replace("’", "'"))
    if not s or len(s) > 60 or _BULLET.match(line) and not line.strip().startswith("#"):
        return None
    for kind, pattern in _HEADINGS:
        if pattern.fullmatch(s):
            return kind
    return None


def _lines(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        for part in _JOINED.split(raw):
            if part.strip():
                out.append(part.rstrip())
    return out


def read(text: str | None) -> Requirements:
    """The must-haves and preferred items a description lists, in order, each once."""
    req = Requirements()
    if not text:
        return req
    section, title, seen = OTHER, None, set()
    for line in _lines(text):
        kind = _heading(line)
        if kind is not None:
            section, title = kind, line.strip().strip("*_#:").strip().rstrip(":").strip()
            continue
        if _FACT_LINE.match(line.strip()):
            section, title = OTHER, None
            continue
        item = _BULLET.sub("", line).strip()
        if len(item) < 2:
            continue
        lower = item.lower()
        if "highlighted with" in lower:  # Naukri: "Skills highlighted with '' are preferred keyskills"
            continue
        if (
            section == PREFERRED
            or _SAYS_PREFERRED.search(lower)
            and not lower.startswith("preferred candidate")
        ):
            where = PREFERRED
        elif section == MUST or _SAYS_MUST.search(lower):
            where = MUST
        else:
            continue
        key = lower[:80]
        if key in seen:
            continue
        seen.add(key)
        (req.must if where == MUST else req.preferred).append(Item(item[:MAX_ITEM], where, title))
    return req


# --- Checking them against a resume -------------------------------------------------------------------------

MET, PARTLY, MISSING, UNCLEAR = "met", "partly", "missing", "unclear"


@dataclass(frozen=True)
class Check:
    text: str
    status: str  # met | partly | missing | unclear (names no skill or degree we can check)
    missing: tuple[str, ...] = ()  # the skills it names that the resume doesn't show


def check(item: Item, resume_text: str, resume_skills: set[str], key_skills: list[str]) -> Check:
    """Whether a resume (lower-cased text) shows one requirement: its degree, or the skills it names."""
    from app.modules.matching import skills as sk  # skills imports taxonomy; keep this module light to import

    wanted = degree_in(item.text)
    if wanted and wanted[0] >= 2:
        have = degree_in(resume_text)
        ok = have is not None and have[0] >= wanted[0]
        return Check(item.text, MET if ok else MISSING, () if ok else (wanted[1],))
    terms = sk.asked_for(item.text.lower(), [], key_skills)
    if not terms:
        return Check(item.text, UNCLEAR)
    mine = {sk.norm(s) for s in key_skills}
    gaps = tuple(
        t for t in terms if not sk.shows(resume_text, resume_skills, t, by_meaning=sk.norm(t) in mine)
    )
    status = MET if not gaps else MISSING if len(gaps) == len(terms) else PARTLY
    return Check(item.text, status, gaps)
