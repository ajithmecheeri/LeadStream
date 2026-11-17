"""Who may use the app, plans and coupons, invites (docs/plan-roles-and-plans.md)."""

import calendar
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import set_user
from app.core.deps import ADMIN_ROLES
from app.core.errors import AppError, NotFound
from app.modules.access.models import Invite, Subscription
from app.modules.access.schemas import AccessOut
from app.modules.users.models import AuditEvent, User


@dataclass(frozen=True)
class Plan:
    id: str
    months: int
    price_inr: int
    label: str


# The user's prices (2026-11-17). Payment comes later (backlog); coupons give 1 or 3 months.
PLANS = (
    Plan("1m", 1, 199, "1 month"),
    Plan("3m", 3, 500, "3 months"),
    Plan("6m", 6, 750, "6 months"),
    Plan("12m", 12, 1200, "1 year"),
)
PLAN_BY_MONTHS = {p.months: p for p in PLANS}
COUPON_MONTHS = (1, 3)
INVITE_DAYS = 14
TOKEN_PREFIX = "bmjinv_"
FREE_FOR = timedelta(days=3650)  # "free access" accounts (tests, the demo): far in the future


@lru_cache
def _free_pattern(pattern: str) -> re.Pattern | None:
    return re.compile(pattern, re.I) if pattern else None


def free_access(email: str) -> bool:
    p = _free_pattern(get_settings().free_access_emails)
    return bool(p and p.search(email))


def effective_access(user: User, now: datetime | None = None) -> datetime | None:
    """Until when this account may use the app; None when it has no running period. Admins: far ahead."""
    now = now or datetime.now(UTC)
    if user.role in ADMIN_ROLES or free_access(user.email):
        return now + FREE_FOR
    return user.access_until if user.access_until and user.access_until > now else None


def why(user: User) -> str:
    """admin | free | plan | none: why the account has access (or not)."""
    if user.role in ADMIN_ROLES:
        return "admin"
    if free_access(user.email):
        return "free"
    return "plan" if effective_access(user) else "none"


def access_out(user: User) -> AccessOut:
    w = why(user)
    return AccessOut(active=w != "none", until=user.access_until if w == "plan" else None, why=w)  # type: ignore[arg-type]


def add_months(start: datetime, months: int) -> datetime:
    m = start.month - 1 + months
    year, month = start.year + m // 12, m % 12 + 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))


async def grant(
    db: AsyncSession, user: User, months: int, kind: str, invite_id: UUID | None = None
) -> Subscription:
    """Add a period to the job seeker: it starts when the running one ends (or now). The session is scoped to
    the user here (subscriptions has row level security)."""
    now = datetime.now(UTC)
    start = user.access_until if user.access_until and user.access_until > now else now
    end = add_months(start, months)
    await set_user(db, user.id)
    sub = Subscription(
        user_id=user.id,
        kind=kind,
        plan=PLAN_BY_MONTHS[months].id,
        months=months,
        starts_at=start,
        ends_at=end,
        invite_id=invite_id,
    )
    db.add(sub)
    user.access_until = end
    db.add(AuditEvent(user_id=user.id, actor="user", event=f"{kind}_{months}m", entity="subscription"))
    await db.flush()
    return sub


# --- Invites ---------------------------------------------------------------------------------------------------


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def link(token: str) -> str:
    return f"{get_settings().public_base_url.rstrip('/')}/invite?token={token}"


async def create_invite(
    db: AsyncSession, by: UUID, email: str, role: str, free_months: int
) -> tuple[Invite, str]:
    if role == "admin":
        free_months = 0  # admins never need a plan
    elif free_months not in (0, *COUPON_MONTHS):
        raise AppError(422, "validation_error", "A coupon is for 1 or 3 months")
    token = TOKEN_PREFIX + secrets.token_urlsafe(24)
    invite = Invite(
        email=email.strip().lower(),
        role=role,
        free_months=free_months,
        token_hash=_hash(token),
        created_by=by,
        expires_at=datetime.now(UTC) + timedelta(days=INVITE_DAYS),
    )
    db.add(invite)
    await db.flush()
    return invite, token


def state(invite: Invite, now: datetime | None = None) -> str:
    """open | accepted | revoked | expired"""
    now = now or datetime.now(UTC)
    if invite.accepted_at:
        return "accepted"
    if invite.revoked_at:
        return "revoked"
    return "expired" if invite.expires_at <= now else "open"


async def open_invite(db: AsyncSession, token: str) -> Invite:
    invite = await db.scalar(select(Invite).where(Invite.token_hash == _hash(token.strip())))
    if invite is None:
        raise NotFound("Invite")
    s = state(invite)
    if s != "open":
        message = {
            "accepted": "This invite was already used",
            "revoked": "This invite was withdrawn",
            "expired": "This invite has expired. Ask for a new one.",
        }[s]
        raise AppError(410, f"invite_{s}", message)
    return invite


async def accept(db: AsyncSession, invite: Invite, user: User) -> None:
    """Give the invite's role and free months to the account it was made for."""
    if user.email.lower() != invite.email.lower():
        raise AppError(
            403, "invite_other_email", f"This invite is for {invite.email}. Sign in with that email."
        )
    now = datetime.now(UTC)
    if invite.role == "admin" and user.role == "job_seeker":
        user.role = "admin"
        db.add(AuditEvent(user_id=user.id, actor="user", event="role_set_admin", entity="user"))
    invite.accepted_at, invite.accepted_by = now, user.id
    if invite.free_months:
        await grant(db, user, invite.free_months, "coupon", invite.id)
    await db.flush()
