"""Pick the parser for an email by its sender and headers (never by subject) and run it. The one exception is
the user's own mail: an AI assistant's job list is recognised by its layout (assistant.py)."""

import email
import re
from email import policy
from email.message import EmailMessage
from email.utils import parseaddr

from app.modules.catalog.parsers.assistant import AssistantAlert
from app.modules.catalog.parsers.base import Parser, ParseResult
from app.modules.catalog.parsers.linkedin import LinkedInDigest, LinkedInSavedJobs
from app.modules.catalog.parsers.naukri import NaukriApplied, NaukriRecommendations, NaukriRecruiterInvite

# Order matters only where senders overlap: invites come from any @naukri.com address.
PARSERS: list[Parser] = [
    LinkedInDigest(),
    LinkedInSavedJobs(),
    NaukriApplied(),
    NaukriRecruiterInvite(),
    NaukriRecommendations(),
]
# Job lists an AI assistant mails from the user's own address: tried only for the user's listed addresses.
ASSISTANT = AssistantAlert()


def load(raw: bytes) -> EmailMessage:
    return email.message_from_bytes(raw, policy=policy.default)  # type: ignore[return-value]


def find_parser(msg: EmailMessage) -> Parser | None:
    return next((p for p in PARSERS if p.matches(msg)), None)


# Gmail's "Forward" button: "---------- Forwarded message ---------" then "From: Name <address>".
_FORWARDED_FROM = re.compile(r"-{5,} Forwarded message -{5,}\s+From:\s*(.+)")
_PORTALS = ("linkedin.com", "naukri.com")
FORWARDED = "X-BrewMyJob-Forwarded"


def unwrap_forward(msg: EmailMessage) -> EmailMessage | None:
    """A hand-forwarded LinkedIn/Naukri alert, re-addressed from its original sender; None otherwise.

    A hand forward loses the portal's DKIM signature and headers, so it is accepted only from an address the
    user listed on Mail setup, and its jobs are unverified (catalog.service). The parsers read the quoted
    alert as usual.
    """
    plain = msg.get_body(("plain",))
    m = _FORWARDED_FROM.search(plain.get_content()) if plain else None
    original = parseaddr(m.group(1).strip())[1].lower() if m else ""
    if original.rpartition("@")[2] not in _PORTALS:
        return None
    copy = load(msg.as_bytes())
    copy.replace_header("From", original)
    copy[FORWARDED] = "gmail"  # the parsers read Gmail's re-rendered layout (see linkedin.py)
    if original == "jobalerts-noreply@linkedin.com":  # LinkedIn's digest is recognised by this header
        copy["X-LinkedIn-Template"] = "email_job_alert_digest"
    return copy


def parse_email(raw: bytes, forwards_from: frozenset[str] = frozenset()) -> ParseResult | None:
    """The jobs in a raw RFC 822 email, or None when no parser recognises it (the message is 'unparsed').

    `forwards_from`: the user's addresses whose hand-forwarded alerts are read as the original (unwrap_forward).
    """
    msg = load(raw)
    own = parseaddr(str(msg.get("From", "")))[1].lower() in forwards_from
    if own:
        msg = unwrap_forward(msg) or msg
    parser = find_parser(msg)
    if parser is None and own and ASSISTANT.matches(msg):
        parser = ASSISTANT  # recognised by its layout: it's the user's own mail, so the sender can't tell
    return parser.parse(msg) if parser else None
