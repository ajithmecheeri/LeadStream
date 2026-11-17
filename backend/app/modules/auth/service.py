"""Sign-up, sign-in, refresh-token rotation and sign-out."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import sessionmaker, set_user
from app.core.errors import AppError, Conflict, Unauthorized
from app.core.security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_inbound_token,
    new_refresh_token,
    verify_password,
)
from app.modules.access.service import access_out, effective_access
from app.modules.auth.schemas import MeOut, NameParts
from app.modules.candidate.models import CandidateProfile
from app.modules.settings.models import NotificationSettings
from app.modules.users.models import AuditEvent, Consent, RefreshToken, User

PRIVACY_NOTICE_VERSION = "2026-10"
CONSENT_PURPOSES = ["job_matching", "document_generation", "notifications"]

# A fixed hash so that a login for an unknown email costs the same time as a wrong password.
_DUMMY_HASH = hash_password("not-a-real-password-0000")


def forwarding_address(user: User) -> str:
    return f"alerts-{user.inbound_token}@{get_settings().inbound_domain}"


def me_out(user: User) -> MeOut:
    return MeOut(
        id=user.id,
        email=user.email,
        name=user.name,
        first_name=user.first_name,
        middle_name=user.middle_name,
        last_name=user.last_name,
        role=user.role,
        access=access_out(user),
        timezone=user.timezone,
        forwarding_address=forwarding_address(user),
        created_at=user.created_at,
    )


def validate_timezone(tz: str) -> str:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise AppError(
            422, "validation_error", "Unknown time zone", [{"field": "timezone", "message": tz}]
        ) from e
    return tz


def full_name(first: str, middle: str | None, last: str | None) -> str:
    return " ".join(p for p in (first, middle, last) if p)


def set_name(user: User, first: str, middle: str | None, last: str | None) -> None:
    user.first_name, user.middle_name, user.last_name = first, middle, last
    user.name = full_name(first, middle, last)


async def signup(
    db: AsyncSession,
    email: str,
    names: NameParts,
    password: str,
    whatsapp_number: str | None = None,
    job_locations: list[str] | None = None,
) -> User:
    """`whatsapp_number` (optional, normalised): saved unverified; alerts start once it is verified in Settings.
    `job_locations`: where the user wants to work (required by the sign-up form; the demo seed has its own)."""
    if await db.scalar(select(User.id).where(User.email == email)):
        raise Conflict("email_taken", "An account with this email already exists")
    user = User(
        id=uuid4(),
        email=email,
        password_hash=hash_password(password),
        inbound_token=new_inbound_token(),
    )
    set_name(user, names.first_name, names.middle_name, names.last_name)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as e:  # lost a race on email, or (very unlikely) the inbound token
        raise Conflict("email_taken", "An account with this email already exists") from e
    await db.refresh(user)

    # Private rows are written under the new user's RLS scope.
    await set_user(db, user.id)
    db.add_all(
        [
            CandidateProfile(user_id=user.id, skills=[], domains=[], job_locations=list(job_locations or [])),
            NotificationSettings(user_id=user.id, whatsapp_number=whatsapp_number),
            Consent(user_id=user.id, notice_version=PRIVACY_NOTICE_VERSION, purposes=CONSENT_PURPOSES),
            AuditEvent(user_id=user.id, actor="user", event="signup", entity="user"),
        ]
    )
    await db.flush()
    return user


# Failed sign-ins per email, kept in memory. Phase 1 runs one API process; Phase 2 moves this to Redis.
MAX_FAILED_LOGINS = 10
FAILED_WINDOW = timedelta(minutes=15)
_failed: dict[str, list[datetime]] = {}


def _recent_failures(email: str) -> list[datetime]:
    cutoff = datetime.now(UTC) - FAILED_WINDOW
    recent = [t for t in _failed.get(email, []) if t > cutoff]
    _failed[email] = recent
    return recent


async def authenticate(db: AsyncSession, email: str, password: str) -> User:
    key = email.lower()
    if len(_recent_failures(key)) >= MAX_FAILED_LOGINS:
        raise AppError(429, "too_many_attempts", "Too many failed sign-ins. Try again in 15 minutes.")
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        verify_password(_DUMMY_HASH, password)
        _failed[key].append(datetime.now(UTC))
        raise Unauthorized("Email or password is incorrect", code="bad_credentials")
    if not verify_password(user.password_hash, password):
        _failed[key].append(datetime.now(UTC))
        db.add(AuditEvent(user_id=user.id, actor="user", event="login_failed", entity="user"))
        raise Unauthorized("Email or password is incorrect", code="bad_credentials")
    _failed.pop(key, None)
    if user.status != "active":
        raise AppError(403, "account_disabled", "This account is disabled")
    db.add(AuditEvent(user_id=user.id, actor="user", event="login", entity="user"))
    return user


async def issue_tokens(
    db: AsyncSession,
    user: User,
    client: str,
    user_agent: str | None,
    ip: str | None,
    family_id: UUID | None = None,
) -> tuple[str, int, str]:
    access, ttl = create_access_token(user.id, user.role, effective_access(user))
    raw, digest = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid4(),
            token_hash=digest,
            client=client,
            expires_at=datetime.now(UTC) + timedelta(days=get_settings().refresh_token_days),
            user_agent=(user_agent or "")[:300] or None,
            ip=ip,
        )
    )
    await db.flush()
    return access, ttl, raw


async def rotate(
    db: AsyncSession, raw: str, user_agent: str | None, ip: str | None
) -> tuple[User, str, int, str]:
    """Exchange a refresh token for a new pair. Presenting an already-rotated token revokes the whole family."""
    now = datetime.now(UTC)
    digest = hash_refresh_token(raw)
    # Plain read first (no row lock), so the reuse path can revoke in its own transaction without deadlocking.
    token = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == digest))
    if token is None or token.revoked_at is not None or token.expires_at <= now:
        raise Unauthorized("Session expired, please sign in again", code="refresh_invalid")
    if token.rotated_at is None:
        # Lock, then re-check: two tabs refreshing at once must not both succeed. The loser just
        # gets a 401 (no family revocation: we hold the row lock, and it isn't theft).
        token = await db.scalar(
            select(RefreshToken)
            .where(RefreshToken.id == token.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if token.rotated_at is not None or token.revoked_at is not None:
            raise Unauthorized("Session expired, please sign in again", code="refresh_invalid")
    else:
        # Possible token theft. Revoke in a separate transaction so it survives this request's rollback.
        async with sessionmaker()() as other, other.begin():
            await revoke_family(other, token.family_id)
            other.add(
                AuditEvent(
                    user_id=token.user_id, actor="system", event="refresh_reuse_detected", entity="session"
                )
            )
        raise Unauthorized("Session expired, please sign in again", code="refresh_reused")
    user = await db.get(User, token.user_id)
    if user is None or user.status != "active":
        raise Unauthorized("Session expired, please sign in again", code="refresh_invalid")
    token.rotated_at = now
    access, ttl, new_raw = await issue_tokens(
        db, user, token.client, user_agent, ip, family_id=token.family_id
    )
    return user, access, ttl, new_raw


async def revoke_family(db: AsyncSession, family_id: UUID) -> None:
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def logout(db: AsyncSession, raw: str | None) -> None:
    if not raw:
        return
    token = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw)))
    if token is not None:
        await revoke_family(db, token.family_id)
