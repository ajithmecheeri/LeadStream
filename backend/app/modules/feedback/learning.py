"""What "Not for me" teaches (milestone 13 part A, loop 1 in docs/milestones.md: for the user, right away).

A reason about the job's company, city, field or level becomes one of the user's learned preferences; matching
then caps jobs like it at 40 (Other jobs) and says why. The user sees every preference on Profile and removes
it with one click; nothing changes the rules for other users. Salary, "applied elsewhere" and "other" are only
recorded (the admin review queue, part C, will read them).

Guards, so one click can't hide a whole search:
- **field**: only a field the user's own background isn't in (a technology leader saying "wrong field" on an
  engineering job teaches nothing);
- **level**: one step above (too junior) or below (too senior) that job's level, from its title. Too junior caps
  lower levels outright, but jobs at that same level only when they ask for under SENIOR_YEARS of experience
  (user, 2026-11-11: "Any Director roles with 10+ years you can cap; they will have less salary as well". One
  "too junior" on a Program Director had capped every Director job, including the 15+ and 20+ year ones; then
  "Make it Director less than 12 years"; then "experience difference you can reduce the fitment 10-20%": those
  jobs lose 10-20% of their score instead of being capped, see years_cut);
- **location**: only named cities; remote jobs are never capped by a city;
- **company**: only a named company (not "Confidential" or an agency's anonymous client).
"""

import re
from dataclasses import dataclass

from app.modules.jobs.duplicates import poster
from app.modules.matching import taxonomy
from app.modules.networking.companies import company_key, matches

REASONS = {
    "field": "Not my field",
    "too_junior": "Too junior",
    "too_senior": "Too senior",
    "location": "Location doesn't work",
    "company": "Not this company",
    "salary": "Salary too low",
    "applied_elsewhere": "Already applied elsewhere",
    "other": "Something else",
}
LEVEL_NAMES = {
    1: "individual contributor",
    2: "lead",
    3: "manager",
    4: "senior manager",
    5: "director",
    6: "senior director / head",
    7: "VP",
    8: "SVP",
    9: "C-level",
}


@dataclass(frozen=True)
class Pref:
    kind: str  # company | location | field | level_min | level_max
    value: str
    label: str


def _city_name(key: str) -> str:
    return key.title()


def learn(
    reason: str, title: str, company: str | None, location: str | None, own_families: set[str]
) -> list[Pref]:
    """The preferences one "Not for me" teaches (often none)."""
    if reason == "company" and company and poster(company) == "company":
        return [Pref("company", company, f"Jobs at {company}")]
    if reason == "location":
        found, _ = taxonomy.cities(location)
        return [Pref("location", c, f"Jobs in {_city_name(c)}") for c in sorted(found)]
    if reason == "field":
        new = taxonomy.families(title) - own_families
        return [Pref("field", f, f"{f.title()} roles") for f in sorted(new)] if len(new) == 1 else []
    level = taxonomy.seniority(title)
    if level is None:
        return []
    if reason == "too_junior" and level < 9:
        name = LEVEL_NAMES[level]
        label = f"Roles below {name} level ({name} roles asking for under {SENIOR_YEARS} years score 10-20% lower)"
        return [Pref("level_min", str(level + 1), label)]
    if reason == "too_senior" and level > 1:
        return [Pref("level_max", str(level - 1), f"Roles above {LEVEL_NAMES[level - 1]} level")]
    return []


# A job at the level marked too junior still counts when it asks for at least this many years (user, 2026-11-11:
# "Make it Director less than 12 years"; it was 15).
SENIOR_YEARS = 12
_YEARS_ASKED = re.compile(
    r"(?:at least|minimum(?: of)?|over|more than)\s+(\d{1,2})\s*\+?\s*(?:years|yrs)|(\d{1,2})\s*\+\s*(?:years|yrs)"
    r"|(\d{1,2})\s*(?:-|–|to)\s*\d{1,2}\s*(?:years|yrs)",
    re.I,
)


def years_asked(experience: str | None, text: str | None = None) -> int | None:
    """The minimum years of experience a job asks for: from its experience field ("15-20 Yrs", "20+ years"), or
    else the most its description asks for anywhere ("At least 7 years…", "10+ years…" → 10). None if unstated."""
    for source in (experience, text):
        found = [int(next(g for g in m.groups() if g)) for m in _YEARS_ASKED.finditer(source or "")]
        found = [n for n in found if 1 <= n <= 40]
        if found:
            return found[0] if source is experience else max(found)
    if m := re.search(r"\d{1,2}", experience or ""):
        return int(m.group(0))
    return None


def years_cut(prefs: list[Pref], title: str, years: int | None) -> float:
    """The share of the score a job loses for asking fewer years than the user's level calls for: a job at the
    level the user marked too junior asking for under SENIOR_YEARS (user, 2026-11-11: "experience difference you
    can reduce the fitment 10-20%"). 10% within 3 years of it, 20% further below; nothing when unstated."""
    level = taxonomy.seniority(title)
    if years is None or level is None or years >= SENIOR_YEARS:
        return 0.0
    if not any(p.kind == "level_min" and level == int(p.value) - 1 for p in prefs):
        return 0.0
    return 0.10 if years >= SENIOR_YEARS - 3 else 0.20


def matching(
    prefs: list[Pref], title: str, company: str | None, location: str | None, years: int | None = None
) -> Pref | None:
    """The first learned preference this job falls under, or None. `years`: the years of experience it asks for
    (years_asked)."""
    companies = {company_key(p.value): p for p in prefs if p.kind == "company"}
    if company and (hit := matches(company, {k: p for k, p in companies.items() if k})):
        return companies[hit[0]]
    level = taxonomy.seniority(title)
    for p in prefs:
        if p.kind == "level_min" and level is not None and level < int(p.value):
            # Lower levels only: the level marked too junior itself loses a share instead (years_cut).
            if level < int(p.value) - 1:
                return p
        if p.kind == "level_max" and level is not None and level > int(p.value):
            return p
    fields = taxonomy.families(title)
    for p in prefs:
        if p.kind == "field" and fields and fields <= {p.value}:
            return p
    found, _ = taxonomy.cities(location)
    excluded = {p.value: p for p in prefs if p.kind == "location"}
    if found and not taxonomy.is_remote(location) and found <= set(excluded):
        return excluded[sorted(found)[0]]
    return None
