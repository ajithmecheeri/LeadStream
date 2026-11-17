"""Short notes for the user to copy into LinkedIn. Templates, not AI (LLD): they use only the job's title and
company and the user's own profile headline, so they can't claim anything the profile doesn't support."""

import re
from urllib.parse import quote

INVITE_LIMIT = 300  # LinkedIn's limit for a note on an invitation


def _about(headline: str | None) -> str:
    return f" A little about me: {headline.strip().rstrip('.')}." if headline and headline.strip() else ""


def _sign(me: str | None) -> str:
    return f"\n{me}" if me else ""


def warm(first: str | None, company: str, job_title: str, headline: str | None, me: str | None) -> str:
    """To a 1st-degree connection at the company: a message, so no length limit, but kept short."""
    hi = f"Hi {first}," if first else "Hi,"
    return (
        f"{hi} I saw that {company} is hiring a {job_title} and I'm interested in the role.{_about(headline)} "
        "Would you be open to a quick chat about the team, or to referring me if you think I'd fit?"
        f" Thanks!{_sign(me)}"
    )


def target(company: str, job_title: str, headline: str | None, me: str | None, own: str | None = None) -> str:
    """An invitation note to someone the user doesn't know yet: at most 300 characters. `own`: the note the user
    wrote on Networking (user feedback 2026-11-11), used as written, signed when the name still fits."""
    if own and own.strip():
        own = own.strip()
        return (own + _sign(me) if len(own + _sign(me)) <= INVITE_LIMIT else own)[:INVITE_LIMIT]
    note = (
        f"Hi, I'm interested in the {job_title} role at {company}.{_about(headline)} I'd be glad to connect."
    )
    note += _sign(me)
    if len(note) > INVITE_LIMIT:  # a long headline: drop it rather than cut a sentence
        note = f"Hi, I'm interested in the {job_title} role at {company} and would be glad to connect.{_sign(me)}"
    return note[:INVITE_LIMIT]


def followup(first: str | None, company: str | None, job_title: str | None, me: str | None) -> str:
    hi = f"Hi {first}," if first else "Hi,"
    about = f" about the {job_title} role at {company}" if job_title and company else ""
    return f"{hi} just following up on my note{about}. Happy to share more if it's useful. Thanks!{_sign(me)}"


_TECH = re.compile(r"engineer|technolog|architect|\bai\b|data|platform|software|cloud|devops|security|\bit\b")
_PRODUCT = re.compile(r"product")


def target_role(job_title: str) -> str:
    """Who to look for at a company with no connection: the likely hiring manager, else a recruiter."""
    t = job_title.lower()
    if re.search(r"\b(chief|cto|ceo|cfo|coo|cpo|president)\b", t) and "vice president" not in t:
        return "CEO"
    senior = re.search(r"\b(vp|vice president|svp|head|director|gm|general manager)\b", t)
    if senior and _PRODUCT.search(t):
        return "Chief Product Officer"
    if senior and _TECH.search(t):
        return "CTO"
    return "Talent Acquisition"


def people_search_url(keywords: str) -> str:
    """A LinkedIn people search the user opens in their own browser. BrewMyJob never runs it."""
    return f"https://www.linkedin.com/search/results/people/?keywords={quote(keywords)}"


def applied(company: str, job_title: str, headline: str | None, me: str | None) -> str:
    """An invitation note after applying (user feedback 2026-11-15): at most 300 characters."""
    note = (
        f"Hi, I recently applied for the {job_title} role at {company}.{_about(headline)} "
        "I'd be glad to connect and learn more about the team."
    ) + _sign(me)
    if len(note) > INVITE_LIMIT:
        note = (
            f"Hi, I recently applied for the {job_title} role at {company} and would be glad to connect."
            + _sign(me)
        )
    return note[:INVITE_LIMIT]


def _function(job_title: str) -> str | None:
    t = job_title.lower()
    if _PRODUCT.search(t):
        return "product"
    if _TECH.search(t):
        return "(engineering OR technology)"
    return None


def people_searches(company: str, job_title: str) -> list[tuple[str, str, str]]:
    """LinkedIn people searches at a company the user applied to (user feedback 2026-11-15): HR and recruiters,
    leaders in the job's function, and the likely hiring manager. (kind, label, url); the user opens them."""
    at = f'"{company}"'
    out = [("hr", "HR & recruiters", people_search_url(f'(recruiter OR "talent acquisition" OR HR) {at}'))]
    func = _function(job_title)
    leaders = "(director OR head OR VP OR chief)" + (f" {func}" if func else "")
    out.append(("leaders", "Leaders", people_search_url(f"{leaders} {at}")))
    role = target_role(job_title)
    if role != "Talent Acquisition":
        out.append(("hiring_manager", role, people_search_url(f'"{role}" {at}')))
    return out
