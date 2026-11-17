"""Which places are in the service's country (India for now: decision 2), and remote work.

The city aliases are the main app's (backend/app/modules/matching/taxonomy.py, CITY_ALIASES), copied so the
service stands alone.
"""

import re

CITY_ALIASES: list[list[str]] = [
    ["bengaluru", "bangalore", "bengaluru east", "bangalore urban", "bengaluru urban"],
    ["mumbai", "bombay", "navi mumbai", "thane"],
    ["delhi", "new delhi", "delhi ncr", "ncr"],
    ["gurugram", "gurgaon"],
    ["noida", "greater noida"],
    ["chennai", "madras"],
    ["kolkata", "calcutta"],
    ["hyderabad", "secunderabad"],
    ["pune"],
    ["kochi", "cochin"],
    ["thiruvananthapuram", "trivandrum"],
    ["ahmedabad"],
    ["jaipur"],
    ["coimbatore"],
    ["chandigarh", "mohali"],
    ["indore"],
    ["kozhikode", "calicut"],
]
_CITY = {alias: names[0] for names in CITY_ALIASES for alias in names}
_INDIA = re.compile(r"\b(india|ind)\b", re.I)
REMOTE_WORDS = ("remote", "work from home", "wfh", "anywhere")


def has(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![\w&]){re.escape(phrase)}(?![\w&])", text) is not None


def cities(location: str | None) -> set[str]:
    loc = (location or "").lower()
    found = set()
    for part in re.split(r"[,/;|()]+", loc):
        part = part.strip()
        if part in _CITY:
            found.add(_CITY[part])
        elif part:
            found |= {city for alias, city in _CITY.items() if has(part, alias)}
    return found


def in_scope(*locations: str | None) -> bool:
    """Any of the locations is in India (the country or one of its cities)."""
    return any(loc and (_INDIA.search(loc) or cities(loc)) for loc in locations)


def is_remote(text: str | None) -> bool:
    t = (text or "").lower()
    return any(has(t, w) for w in REMOTE_WORDS)
