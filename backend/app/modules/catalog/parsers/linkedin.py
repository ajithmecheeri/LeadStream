"""LinkedIn job-alert digest (`X-LinkedIn-Template: email_job_alert_digest_*`), and the saved-jobs reminder
(LinkedInSavedJobs, below).

The HTML part is the source: each job is a `data-test-id="job-card"` block with the title link, a
"Company · Location (Work model)" line, an optional salary line and "flavor" lines ("2 connections").
The plain-text part has the same jobs without work model or salary; it's the fallback and a cross-check.

A hand forward from Gmail (testing only, see registry.unwrap_forward) loses the `data-test-id` markers, and
Gmail writes its own plain text from the HTML: each link on its own line as `<https://...>`, images as
`[image: ...]`, no dashed separators. `_forwarded_cards` reads that layout instead.
"""

import re
from email.message import EmailMessage

from app.modules.catalog.parsers.base import (
    JobCard,
    ParseResult,
    clean,
    html_body,
    sender_domain,
    text_body,
)
from app.modules.catalog.parsers.normalize import split_location

_JOB_LINK = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)")
_SALARY = re.compile(r"[₹$€£]|\b(?:INR|USD|lakh|LPA)\b|/\s*(?:year|yr|month|mo|hour|hr)\b", re.I)
_ALERT = re.compile(r"Your job alert for\s+(.+)")
_LINK_LINE = re.compile(r"<(https?://[^>\s]+)>")
_IMAGE = re.compile(r"\[image:[^\]]*\]", re.S)


def _url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs/view/{job_id}/"


class LinkedInDigest:
    name = "linkedin_digest"
    version = 1

    def matches(self, msg: EmailMessage) -> bool:
        return sender_domain(msg) == "linkedin.com" and str(msg.get("X-LinkedIn-Template", "")).startswith(
            "email_job_alert_digest"
        )

    def parse(self, msg: EmailMessage) -> ParseResult:
        if msg.get("X-BrewMyJob-Forwarded"):
            # Gmail re-renders the text; other mail apps may keep LinkedIn's own (read without the header block).
            cards = (
                self._html_cards(msg) or self._forwarded_cards(msg) or self._text_cards(msg, forwarded=True)
            )
            warnings = [] if cards else ["hand forward: no job cards found"]
            return ParseResult(f"{self.name}@{self.version}", cards, self._alert_name(msg), warnings)
        from_html, from_text = self._html_cards(msg), self._text_cards(msg)
        warnings = []
        if from_html and from_text:
            seen_html = {(c.source_job_id, c.title, c.company) for c in from_html}
            seen_text = {(c.source_job_id, c.title, c.company) for c in from_text}
            if seen_html != seen_text:
                warnings.append("HTML and plain-text parts list different jobs")
        cards = from_html or from_text
        if not from_html and from_text:
            warnings.append("no job cards in HTML; used the plain-text part")
        return ParseResult(f"{self.name}@{self.version}", cards, self._alert_name(msg), warnings)

    def _html_cards(self, msg: EmailMessage) -> list[JobCard]:
        soup = html_body(msg)
        if soup is None:
            return []
        cards: dict[str, JobCard] = {}
        for block in soup.select('[data-test-id="job-card"]'):
            link = next((a for a in block.find_all("a", href=True) if _JOB_LINK.search(a["href"])), None)
            if link is None:
                continue
            job_id = _JOB_LINK.search(link["href"]).group(1)
            # Innermost links and paragraphs only: an outer <a> wraps the whole card.
            leaves = [el for el in block.find_all(["a", "p"]) if not el.find(["a", "p", "table"])]
            lines = [t for t in (clean(el.get_text(" ")) for el in leaves) if t]
            title = next((t for t in lines if " · " not in t), None)
            company_line = next((t for t in lines if " · " in t), None)
            if not title or not company_line or job_id in cards:
                continue
            company, _, place = company_line.partition(" · ")
            location, model = split_location(place)
            salary = next((t for t in lines if t not in (title, company_line) and _SALARY.search(t)), None)
            flavor = [clean(p.get_text(" ")) for p in block.select("p.job-card-flavor__detail")]
            cards[job_id] = JobCard(
                source="linkedin",
                source_job_id=job_id,
                title=title,
                company=company.strip() or None,
                location=location,
                work_model=model,
                salary=salary,
                lead="alert",
                canonical_url=_url(job_id),
                card_lines=tuple(f for f in flavor if f),
            )
        return list(cards.values())

    def _text_cards(self, msg: EmailMessage, forwarded: bool = False) -> list[JobCard]:
        """Blocks of 'title / company / location / [extra lines] / View job: <url>', split by dashes."""
        cards: dict[str, JobCard] = {}
        body = text_body(msg).split("See all jobs on LinkedIn")[0]
        if forwarded:  # drop "---------- Forwarded message ---------", From:, Date:, Subject:, To:
            after = body.split("Forwarded message", 1)[-1]
            body = after.split("\n\n", 1)[-1] if "\n\n" in after else after
        for block in re.split(r"\n-{10,}\s*\n", body):
            m = _JOB_LINK.search(block)
            lines = [clean(x) for x in block.splitlines()]
            lines = [x for x in lines if x and not x.startswith(("View job:", "Your job alert for"))]
            lines = [x for x in lines if not re.match(r"^\d+ new jobs? match", x)]
            if not m or len(lines) < 3 or m.group(1) in cards:
                continue
            job_id = m.group(1)
            cards[job_id] = JobCard(
                source="linkedin",
                source_job_id=job_id,
                title=lines[0],
                company=lines[1],
                location=lines[2],
                lead="alert",
                canonical_url=_url(job_id),
                card_lines=tuple(lines[3:]),
            )
        return list(cards.values())

    def _forwarded_cards(self, msg: EmailMessage) -> list[JobCard]:
        """Gmail's plain text of a forwarded alert. A job's lines sit between links to that job:

            [image: Acme]  <.../jobs/view/1>  VP Engineering  <.../jobs/view/1>  Acme · Bengaluru (Hybrid)
            Actively recruiting  <.../jobs/view/1>

        so the text before each job link belongs to that job; text before any other link (the header, "See all
        jobs", the footer) is dropped.
        """
        body = _IMAGE.sub("", text_body(msg))
        lines: dict[str, list[str]] = {}
        start = 0
        for link in _LINK_LINE.finditer(body):
            job = _JOB_LINK.search(link.group(1))
            chunk = body[start : link.start()]
            start = link.end()
            if job:
                found = [clean(x) for x in chunk.splitlines()]
                lines.setdefault(job.group(1), []).extend(x for x in found if x)
        cards = []
        for job_id, found in lines.items():
            company_line = next((t for t in found if " · " in t), None)
            title = next((t for t in found if " · " not in t), None)
            if not title or not company_line:
                continue
            company, _, place = company_line.partition(" · ")
            location, model = split_location(place)
            extra = [t for t in found if t not in (title, company_line)]
            salary = next((t for t in extra if _SALARY.search(t)), None)
            cards.append(
                JobCard(
                    source="linkedin",
                    source_job_id=job_id,
                    title=title,
                    company=company.strip() or None,
                    location=location,
                    work_model=model,
                    salary=salary,
                    lead="alert",
                    canonical_url=_url(job_id),
                    card_lines=tuple(t for t in extra if t != salary),
                )
            )
        return cards

    def _alert_name(self, msg: EmailMessage) -> str | None:
        # The plain text has the full search ("vice president in Bangalore Urban"); the HTML only the keywords.
        m = _ALERT.search(text_body(msg))
        if m:
            # A forward's text wraps the name over lines between *...*: take it up to the closing star.
            if m.group(1).lstrip().startswith("*"):
                return clean(text_body(msg)[m.start(1) :].lstrip().lstrip("*").split("*", 1)[0])
            return clean(m.group(1))
        soup = html_body(msg)
        header = soup.select_one('[data-test-id="email-header"]') if soup else None
        m = _ALERT.search(clean(header.get_text(" "))) if header else None
        return clean(m.group(1)) if m else None


class LinkedInSavedJobs:
    """LinkedIn's reminder about jobs the user saved (`X-LinkedIn-Template: email_jobs_saved_job_reminder_*`,
    from jobs-noreply@linkedin.com): "Your saved job at Wipro is still available", then "Your other saved jobs".

    Not new jobs from a search, but the user's own picks, so they are read like alert cards. A job the user
    already has keeps its status (one row per user and job), so an applied job stays in Applied. The plain text
    has each job as 'title / company / location / [flavor lines] / View job: <url>'; the lines before the title
    (the reminder sentence, "Your other saved jobs", connections to message) are not part of it.
    """

    name = "linkedin_saved_jobs"
    version = 1

    def matches(self, msg: EmailMessage) -> bool:
        return sender_domain(msg) == "linkedin.com" and str(msg.get("X-LinkedIn-Template", "")).startswith(
            "email_jobs_saved_job_reminder"
        )

    def parse(self, msg: EmailMessage) -> ParseResult:
        cards: dict[str, JobCard] = {}
        lines = [clean(x) for x in text_body(msg).splitlines()]
        for i, line in enumerate(lines):
            m = _JOB_LINK.search(line) if line.startswith("View job:") else None
            if not m or m.group(1) in cards:
                continue
            block: list[str] = []
            for prev in reversed(lines[:i]):  # back to the separator or heading before the job
                if prev.startswith("---") or _SAVED_HEADING.search(prev):
                    break
                if prev:  # LinkedIn's plain text may leave blank lines between a job's lines
                    block.insert(0, prev)
            if len(block) < 3:
                continue
            location, model = split_location(block[2])
            cards[m.group(1)] = JobCard(
                source="linkedin",
                source_job_id=m.group(1),
                title=block[0],
                company=block[1],
                location=location,
                work_model=model,
                lead="alert",
                canonical_url=_url(m.group(1)),
                card_lines=tuple(block[3:]),
            )
        warnings = [] if cards else ["saved-jobs reminder: no jobs found"]
        return ParseResult(f"{self.name}@{self.version}", list(cards.values()), None, warnings)


_SAVED_HEADING = re.compile(r"saved job .* still available|^Your other saved jobs$|^Apply now$", re.I)
