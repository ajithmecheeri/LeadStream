"""Company names, normalised so people and jobs can be matched: "Helix Cloud Systems Pvt. Ltd." and "Helix
Cloud Systems" are the same company. Pure functions (tested without a database)."""

import re

# Words that only say what kind of company it is; dropped from the end of a name.
_SUFFIXES = {
    "pvt", "private", "ltd", "limited", "inc", "incorporated", "llc", "llp", "plc", "corp", "corporation",
    "co", "company", "gmbh", "ag", "sa", "bv", "nv", "india", "group",
}  # fmt: skip
# A truncated job company ("Crescendo Global Le...") matches by prefix only when this much is left.
MIN_PREFIX = 8
# "Accenture" matches "Accenture Song"; "Bank" never matches "Bank of Baroda".
MIN_WORDS_PREFIX = 6


def is_truncated(name: str | None) -> bool:
    return bool(name) and name.rstrip().endswith(("...", "…"))


def company_key(name: str | None) -> str | None:
    """Lower case, '&' as 'and', punctuation gone, legal suffixes and a leading 'the' dropped."""
    if not name:
        return None
    s = name.strip().removesuffix("...").removesuffix("…").lower().replace("&", " and ")
    words = re.sub(r"[^a-z0-9]+", " ", s).split()
    if words and words[0] == "the":
        words = words[1:]
    while len(words) > 1 and words[-1] in _SUFFIXES:
        words.pop()
    return " ".join(words) or None


def _same(a: str, b: str) -> bool:
    """One name is the other plus whole words ("commonwealth bank" / "commonwealth bank of australia"). The
    shorter must be long enough that it isn't just a common word ("bank")."""
    short, long_ = sorted((a, b), key=len)
    return len(short) >= MIN_WORDS_PREFIX and long_.startswith(short + " ")


def matches(job_company: str | None, keys: set[str] | dict) -> list[str]:
    """The connection company keys that are this job's company: the same name, one name with more words, or
    the start of the name when the alert cut it short ("Crescendo Global Le...")."""
    key = company_key(job_company)
    if not key:
        return []
    truncated = is_truncated(job_company) and len(key) >= MIN_PREFIX
    return sorted(k for k in keys if k == key or _same(k, key) or (truncated and k.startswith(key)))


def search_name(name: str | None) -> str | None:
    """The company as people write it on LinkedIn, for a people search: "GE HealthCare India Pvt. Ltd." is "GE
    HealthCare"; a name an alert cut short ("Crescendo Global Le...") loses its partial last word."""
    if not name:
        return None
    s = name.strip()
    words = s.removesuffix("...").removesuffix("…").split()
    if is_truncated(s) and len(words) > 1:
        words = words[:-1]
    while len(words) > 1 and re.sub(r"[^a-z]", "", words[-1].lower()) in _SUFFIXES | {""}:
        words.pop()
    out = " ".join(words).strip(" ,.-")
    return out or None
