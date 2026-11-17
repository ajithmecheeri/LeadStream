"""Pairing codes and extension tokens (milestone 14.3), and the portals the extension never fills.

A code or token carries its user's id ("<prefix><user id, base64url>.<secret>"), so it is checked inside that
user's own RLS scope; only a sha256 of the secret is stored. Codes last 10 minutes and are used once; tokens last
until revoked on Settings.
"""

import base64
import hashlib
import secrets
from urllib.parse import urlsplit
from uuid import UUID

CODE_PREFIX = "bmjpair."
TOKEN_PREFIX = "bmjx."
CODE_MINUTES = 10

# Job portals: the extension refuses to fill on them, and the API refuses to serve it data for them (CLAUDE.md:
# no automation on job portals, not even click-to-fill). Company application systems (Greenhouse, Lever, Ashby,
# SmartRecruiters, Workday…) are allowed. Keep in step with apps/extension/src/blocked.js.
BLOCKED_DOMAINS = (
    "linkedin.com",
    "naukri.com",
    "indeed.com",
    "indeed.co.in",
    "foundit.in",
    "monsterindia.com",
    "glassdoor.com",
    "glassdoor.co.in",
    "iimjobs.com",
    "hirist.tech",
    "hirist.com",
    "instahyre.com",
    "shine.com",
    "timesjobs.com",
    "apna.co",
    "cutshort.io",
    "wellfound.com",
    "angel.co",
)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def make(prefix: str, user_id: UUID) -> tuple[str, str]:
    """A new code or token for this user, and the hash to store."""
    secret = secrets.token_urlsafe(24)
    uid = base64.urlsafe_b64encode(user_id.bytes).decode().rstrip("=")
    return f"{prefix}{uid}.{secret}", hash_secret(secret)


def parse(prefix: str, value: str) -> tuple[UUID, str] | None:
    """(user id, secret hash) from a code or token, or None when it isn't one."""
    value = value.strip()
    if not value.startswith(prefix):
        return None
    uid, _, secret = value[len(prefix) :].partition(".")
    try:
        user_id = UUID(bytes=base64.urlsafe_b64decode(uid + "=" * (-len(uid) % 4)))
    except ValueError:
        return None
    return (user_id, hash_secret(secret)) if len(secret) >= 20 else None


def blocked(url: str | None) -> bool:
    host = (urlsplit(url or "").hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)
