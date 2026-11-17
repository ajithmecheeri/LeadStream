"""Naukri emails: profile recommendations ("Top Openings for …"), recruiter invites ("✉️ Job | …") and the
confirmation after applying ("You applied for 1 job on 12 Nov", with similar jobs).

Neither has stable CSS hooks, so both parsers anchor on links: job-listings links for recommendations,
the `applyBroadcastMail` link and row icons for invites.
"""

import re
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup, Comment, Tag

from app.modules.catalog.parsers.base import JobCard, ParseResult, clean, html_body, sender, sender_domain
from app.modules.catalog.parsers.normalize import experience, split_location, strip_query, work_model
from app.modules.matching import taxonomy

_JOB_LINK = re.compile(r"naukri\.com/(?:jd/)?job-listings-[^?#]*?-(\d{9,})(?:[/?#]|$)")
_SLUG_EXPERIENCE = re.compile(r"-(\d+)-to-(\d+)-years?-\d+$")
_SKIP_PARENTS = {"style", "script", "title", "head"}


def _strings(soup: BeautifulSoup):
    """Visible text pieces in document order, each with the <a> it sits in (or None)."""
    for s in soup.find_all(string=True):
        if isinstance(s, Comment) or (s.parent and s.parent.name in _SKIP_PARENTS):
            continue
        text = clean(s)
        if text:
            yield text, s.find_parent("a")


class NaukriRecommendations:
    name = "naukri_recommendations"
    version = 1

    def matches(self, msg: EmailMessage) -> bool:
        return sender(msg) == "naukrialerts@naukri.com"

    def parse(self, msg: EmailMessage) -> ParseResult:
        soup = html_body(msg)
        cards: list[dict] = []
        seen: set[str] = set()
        outside = False
        current: dict | None = None
        for text, link in _strings(soup) if soup else ():
            href = link.get("href", "") if link else ""
            if text.startswith("Jobs outside your preference"):
                outside, current = True, None
            elif (m := _JOB_LINK.search(href)) and (current is None or m.group(1) != current["id"]):
                # A new job: its first text is the title. Each card is also wrapped in an outer link to the
                # same job, so company and location sit inside a job link too; the id tells them apart.
                current = None
                if m.group(1) not in seen:
                    seen.add(m.group(1))
                    current = {"id": m.group(1), "href": href, "link": link, "title": text, "after": []}
                    current["outside"] = outside
                    cards.append(current)
            elif current is not None and link is current["link"]:
                current["title"] += " " + text
            elif current is not None and "ambitionbox.com" not in href and len(current["after"]) < 2:
                current["after"].append(text)  # company, then location; AmbitionBox ratings are skipped
        result = [self._card(c) for c in cards]
        m = re.search(r"Top Openings for (.+)$", clean(str(msg.get("Subject", ""))))
        warnings = [] if result else ["no job links found"]
        return ParseResult(f"{self.name}@{self.version}", result, m.group(1) if m else None, warnings)

    def _card(self, c: dict) -> JobCard:
        company = c["after"][0] if c["after"] else None
        location, model = split_location(c["after"][1]) if len(c["after"]) > 1 else (None, None)
        url = strip_query(c["href"])
        exp = _SLUG_EXPERIENCE.search(urlsplit(url).path)
        return JobCard(
            source="naukri",
            source_job_id=c["id"],
            title=c["title"],
            company=company,
            company_truncated=bool(company and company.endswith("...")),
            location=location,
            work_model=model,
            experience=experience(*exp.groups()) if exp else None,
            lead="recommendation",
            outside_preference=c["outside"],
            canonical_url=url,
        )


# Rows under the title, identified by their icon image (i3_1.png …).
_ICON_FIELDS = {"i3_1": "location", "i4_1": "experience", "i4": "salary", "i6": "work_model", "i7": "skills"}
_LABELS = {
    "Industry type": "industry",
    "Department": "department",
    "Role": "role",
    "Employment type": "employment_type",
    "Education": "education",
}
# "✉️ Job | VP-AI Senior Leader in [Mumbai, Bengaluru]"; newer invites drop the brackets ("… in Bengaluru"),
# so the title runs to the last " in ".
_INVITE_SUBJECT = re.compile(r"Job\s*\|\s*(.+?)\s+in\s+\[(.+)\]\s*$")
_INVITE_SUBJECT_PLAIN = re.compile(r"Job\s*\|\s*(.+)\s+in\s+(.+?)\s*$")
# Recruiters' padding around the real title: "Exciting job at HCL---- SAP GRC Architect- Bangalore".
_TITLE_PREFIX = re.compile(
    r"^(?:exciting|urgent|great|excellent|hiring)\s+(?:job|opening|opportunity|role)\s+(?:at|with|for)\s+"
    r"[^-|:]+?\s*[-|:]+\s*",
    re.I,
)


_TRAILING_PLACE = re.compile(r"\s*[-–|,]\s*([A-Za-z][A-Za-z .]+?)\s*$")


def _invite_title(title: str, location: str) -> str:
    """The job title without the recruiter's padding, or the city it repeats ("… Architect- Bangalore" for a job
    in Bengaluru)."""
    title = _TITLE_PREFIX.sub("", title).strip()
    m = _TRAILING_PLACE.search(title)
    if m and taxonomy.cities(m.group(1))[0] & taxonomy.cities(location)[0]:
        title = title[: m.start()]
    return title.strip(" -–|,")


def _next_text(el: Tag) -> str:
    """The first visible text after `el`, skipping text inside `el` itself (a label's own words)."""
    for s in el.find_all_next(string=True):
        if clean(s) and not isinstance(s, Comment) and el not in s.parents:
            return clean(s)
    return ""


def _rated_company(soup: BeautifulSoup) -> str | None:
    """The employer named just before its star rating ("HCLTech ★ 3.4 (51426 Reviews)"), when the invite shows
    one."""
    star = soup.find("img", src=re.compile(r"/star\.\w+(?:\?|$)"))
    if star is None:
        return None
    before = next((clean(s) for s in star.find_all_previous(string=True) if clean(s)), "")
    return before if before and not re.search(r"invited to apply|\d", before) else None


def _description(el: Tag) -> str:
    """Paragraphs as lines and list items as '- ' bullets."""
    blocks = el.find_all(["p", "li"])
    if not blocks:
        return clean(el.get_text(" "))
    return "\n".join(("- " if b.name == "li" else "") + clean(b.get_text(" ")) for b in blocks)


class NaukriRecruiterInvite:
    name = "naukri_recruiter_invite"
    version = 1

    def matches(self, msg: EmailMessage) -> bool:
        if sender_domain(msg) != "naukri.com":
            return False
        part = msg.get_body(("html",))
        return bool(part) and "applyBroadcastMail" in part.get_content()

    def parse(self, msg: EmailMessage) -> ParseResult:
        name = f"{self.name}@{self.version}"
        soup = html_body(msg)
        apply = soup.find("a", href=re.compile("applyBroadcastMail")) if soup else None
        subject_line = clean(str(msg.get("Subject", "")))
        subject = _INVITE_SUBJECT.search(subject_line) or _INVITE_SUBJECT_PLAIN.search(subject_line)
        mid = parse_qs(urlsplit(apply["href"]).query).get("mid", [None])[0] if apply else None
        if not soup or not mid or not subject:
            return ParseResult(name, [], warnings=["recruiter invite without a message id or job title"])

        rows: dict[str, str] = {}
        for img in soup.find_all("img", src=True):
            m = re.search(r"/(i\d+(?:_\d+)?)\.\w+$", img["src"].split("?")[0])
            if m and m.group(1) in _ICON_FIELDS:
                rows[_ICON_FIELDS[m.group(1)]] = _next_text(img)

        details = {"recruiter": parseaddr(str(msg.get("From", "")))[0]}
        for td in soup.find_all("td"):
            label = clean(td.get_text(" "))
            if label in _LABELS and not td.find("td"):
                details[_LABELS[label]] = _next_text(td)

        heading = soup.find("strong", string=lambda s: clean(s) == "Job description")
        # The description is the next non-empty cell after the heading's own (spacer cells in between).
        body = heading.find_parent("td").find_next("td") if heading else None
        while body is not None and not clean(body.get_text()):
            body = body.find_next("td")

        exp = re.search(r"(\d+)\s*-\s*(\d+)", rows.get("experience", ""))
        salary = rows.get("salary")
        location = rows.get("location") or subject.group(2)
        card = JobCard(
            source="naukri_rdx",
            source_job_id=mid,
            title=_invite_title(subject.group(1), location),
            # The sender is the recruiter or a Naukri hiring service, not the employer; newer invites name the
            # employer next to its rating.
            company=_rated_company(soup),
            location=location,
            work_model=work_model(rows.get("work_model")),
            salary=None if not salary or salary.lower() == "not disclosed" else salary,
            experience=experience(*exp.groups()) if exp else None,
            skills=tuple(s.strip() for s in rows.get("skills", "").split(",") if s.strip()),
            description=_description(body) if body else None,
            lead="recruiter_invite",
            apply_url=apply["href"],
            details=details,
        )
        return ParseResult(name, [card])


# The job page inside Naukri's click-tracking link (`dl.naukri.com?…&redirect=<url>`); read, never followed. The
# applied job's link has no slug: "job-listings-111126835302".
_ANY_JOB_LINK = re.compile(r"naukri\.com/(?:jd/)?job-listings-(?:[^?#]*-)?(\d{9,})(?:[/?#]|$)")
_RATING = re.compile(r"^(?:\d(?:\.\d)?|null)$")
_APPLIED_ON = re.compile(r"Applied on ([A-Z][a-z]+ \d{1,2}, \d{4})")


def _target(href: str) -> str:
    """The real address behind Naukri's tracking link, or the link itself."""
    if "dl.naukri.com" in href or "tr.naukri.com" in href:
        return parse_qs(urlsplit(href).query).get("redirect", [""])[0]
    return href


class NaukriApplied:
    """ "You applied for 1 job on 12 Nov" (info@naukri.com, user feedback 2026-11-15): the job applied to, which
    is marked Applied on that date, and Naukri's "Similar jobs for you", added as recommendations."""

    name = "naukri_applied"
    version = 1

    def matches(self, msg: EmailMessage) -> bool:
        if sender(msg) != "info@naukri.com":
            return False
        part = msg.get_body(("html",))
        return bool(part) and "Your application was sent" in part.get_content()

    def parse(self, msg: EmailMessage) -> ParseResult:
        name = f"{self.name}@{self.version}"
        soup = html_body(msg)
        cards: list[JobCard] = []
        applied: dict[int, date] = {}
        on = self._applied_on(soup, msg) if soup else None
        seen: set[str] = set()
        for a in soup.find_all("a", href=True) if soup else ():
            url = _target(a["href"])
            m = _ANY_JOB_LINK.search(url)
            if not m or m.group(1) in seen:
                continue
            parts = [clean(s) for s in a.find_all(string=True) if clean(s) and not isinstance(s, Comment)]
            parts = [p for p in parts if not _RATING.match(p)]
            if not parts:
                continue
            seen.add(m.group(1))
            was_applied = "appliedJD" in url
            if was_applied and on:
                applied[len(cards)] = on
            cards.append(self._card(m.group(1), url, parts, was_applied))
        warnings = [] if cards else ["no job links found"]
        if cards and not applied:
            warnings.append("no applied job found")
        return ParseResult(name, cards, None, warnings, applied=applied)

    @staticmethod
    def _applied_on(soup: BeautifulSoup, msg: EmailMessage) -> date | None:
        m = _APPLIED_ON.search(soup.get_text(" "))
        if m:
            try:
                return datetime.strptime(m.group(1), "%B %d, %Y").date()
            except ValueError:
                pass
        sent = msg.get("Date")
        return sent.datetime.date() if sent is not None and getattr(sent, "datetime", None) else None

    @staticmethod
    def _card(job_id: str, url: str, parts: list[str], was_applied: bool) -> JobCard:
        canonical = strip_query(url)
        exp = _SLUG_EXPERIENCE.search(urlsplit(canonical).path)
        company = parts[1] if len(parts) > 1 else None
        location, model = split_location(parts[2]) if len(parts) > 2 else (None, None)
        return JobCard(
            source="naukri",
            source_job_id=job_id,
            title=parts[0],
            company=company,
            company_truncated=bool(company and company.endswith("...")),
            location=location,
            work_model=model,
            experience=experience(*exp.groups()) if exp else None,
            lead="alert" if was_applied else "recommendation",
            canonical_url=canonical,
        )
