"""A role as the user writes it, in Google's search syntax (user, 2026-11-15).

"(Technology Director OR Engineering Director) (Bengaluru OR Bangalore)" becomes
'("Technology Director" OR "Engineering Director") ("Bengaluru" OR "Bangalore")': every alternative is quoted, so
Google matches each as a phrase, and the brackets group them. A plain role ("VP Engineering") is one quoted phrase;
"A OR B" without brackets is grouped as "(A OR B)". OR must be in capitals, as Google wants it ("|" works too).
Brackets inside brackets aren't supported. The result is the same when it goes through again.
"""

import re

_OR = re.compile(r"\s+OR\s+|\s*\|\s*")
MAX_CHARS = 200


class BadQuery(ValueError):
    pass


def _segments(text: str) -> list[str]:
    """The bracketed groups and the plain text between them, in order (brackets kept on the groups)."""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        if ch == "(":
            if depth:
                raise BadQuery("Brackets inside brackets aren't supported")
            if text[start:i].strip():
                out.append(text[start:i])
            depth, start = 1, i
        elif ch == ")":
            if not depth:
                raise BadQuery("A closing bracket has no opening one")
            out.append(text[start : i + 1])
            depth, start = 0, i + 1
    if depth:
        raise BadQuery("A bracket isn't closed")
    if text[start:].strip():
        out.append(text[start:])
    return out


def _quoted(term: str) -> str:
    term = " ".join(term.replace('"', " ").split())
    return f'"{term}"'


def _group(segment: str) -> str:
    inner = segment.strip()
    bracketed = inner.startswith("(") and inner.endswith(")")
    if bracketed:
        inner = inner[1:-1]
    terms = [t for t in _OR.split(inner.strip()) if t.strip(' "')]
    if not terms:
        return ""
    if len(terms) == 1:
        return _quoted(terms[0])
    return "(" + " OR ".join(_quoted(t) for t in terms) + ")"


def google_terms(text: str) -> str:
    """The role in Google's syntax. Raises BadQuery for unbalanced or nested brackets."""
    text = " ".join(text.split())
    parts = [g for s in _segments(text) if (g := _group(s))]
    if not parts:
        raise BadQuery("Write a role")
    out = " ".join(parts)
    if len(out) > MAX_CHARS:
        raise BadQuery(f"At most {MAX_CHARS} characters")
    return out


def names_place(query: str, places: list[str], other_names: dict[str, str]) -> bool:
    """True when the role already says where ("… (Bengaluru OR Bangalore)"): no city is added to its alert."""
    low = query.lower()
    for p in places:
        for name in (p, other_names.get(p.lower(), "")):
            if name and re.search(rf"(?<!\w){re.escape(name.lower())}(?!\w)", low):
                return True
    return False
