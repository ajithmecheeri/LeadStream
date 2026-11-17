"""Where a user wants to work: asked at sign-up (2026-11-14), editable on the Profile."""

MAX_JOB_LOCATIONS = 10


def norm_locations(values: list[str]) -> list[str]:
    """Places as typed, tidied: spaces collapsed, duplicates (any letter case) and blanks dropped."""
    seen, out = set(), []
    for v in values:
        place = " ".join(v.split())
        if place and place.lower() not in seen:
            seen.add(place.lower())
            out.append(place)
    return out


def check_locations(values: list[str]) -> list[str]:
    """For a validator: the tidied places, or ValueError with a message for the form."""
    if any(len(p.strip()) > 60 for p in values):
        raise ValueError("Keep each place under 60 characters")
    places = norm_locations(values)
    if not places:
        raise ValueError("Add at least one place you'd like to work")
    return places
