"""Contacts written in a job's description: an email to send a CV to, a recruiter's LinkedIn profile.

Read on request from the text the user sees (the catalog description, or the one they pasted); nothing is stored.
BrewMyJob never writes to these people: the job page only shows them, with mailto and profile links.
"""

import re
from dataclasses import dataclass

_EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])")
_PROFILE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/([A-Za-z0-9_%-]{2,100})/?", re.I)
# Addresses that never reach a person.
_NOT_A_PERSON = re.compile(
    r"^(no-?reply|do-?not-?reply|donotreply|mailer-daemon|privacy|unsubscribe)\b", re.I
)
MAX_EACH = 5


@dataclass(frozen=True)
class Found:
    kind: str  # email | linkedin
    value: str  # the address, or the profile's name part ("priya-nair")
    url: str  # mailto:… or the profile link
    context: str | None  # the sentence it appeared in, shortened


def _context(text: str, start: int, end: int) -> str | None:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line = " ".join(text[line_start : line_end if line_end != -1 else len(text)].split())
    if len(line) > 140:
        mid = start - line_start
        lo, hi = max(0, mid - 60), mid + 80
        line = ("…" if lo else "") + line[lo:hi].strip() + ("…" if hi < len(line) else "")
    return line or None


def found_in(text: str | None, known: set[str] = frozenset()) -> list[Found]:
    """Emails and LinkedIn profiles in the text, first seen first, skipping `known` (already saved, lower case)."""
    if not text:
        return []
    out: list[Found] = []
    seen = set(known)
    emails = 0
    for m in _EMAIL.finditer(text):
        email = m.group(0).rstrip(".").lower()
        if email in seen or _NOT_A_PERSON.match(email) or emails >= MAX_EACH:
            continue
        seen.add(email)
        emails += 1
        out.append(Found("email", email, f"mailto:{email}", _context(text, m.start(), m.end())))
    profiles = 0
    for m in _PROFILE.finditer(text):
        url = f"https://www.linkedin.com/in/{m.group(1)}"
        if url.lower() in seen or profiles >= MAX_EACH:
            continue
        seen.add(url.lower())
        profiles += 1
        out.append(Found("linkedin", m.group(1), url, _context(text, m.start(), m.end())))
    return out
