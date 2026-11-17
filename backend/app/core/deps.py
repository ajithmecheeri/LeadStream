"""Request dependencies: the signed-in user and an RLS-scoped database session."""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import user_scope
from app.core.errors import AppError, Unauthorized
from app.core.security import decode_access_token

ADMIN_ROLES = ("admin", "super_admin")


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    role: str
    access_until: int | None = None  # epoch seconds; see require_access

    @property
    def is_admin(self) -> bool:
        return self.role in ADMIN_ROLES


def current_user(request: Request) -> CurrentUser:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise Unauthorized()
    try:
        claims = decode_access_token(header[7:].strip())
    except jwt.ExpiredSignatureError as e:
        raise Unauthorized("Session expired", code="token_expired") from e
    except jwt.PyJWTError as e:
        raise Unauthorized("Invalid token", code="invalid_token") from e
    user = CurrentUser(
        id=UUID(claims["sub"]), role=claims.get("role", "job_seeker"), access_until=claims.get("acc")
    )
    request.state.user_id = user.id
    return user


def require_admin(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
    """Admins and the super admin (Job sources)."""
    if not user.is_admin:
        raise AppError(403, "forbidden", "Admins only")
    return user


def require_super_admin(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
    """The super admin only (Admin settings, invites)."""
    if user.role != "super_admin":
        raise AppError(403, "forbidden", "For the super admin only")
    return user


def require_access(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
    """A job seeker needs a running plan or coupon period; admins never do (docs/plan-roles-and-plans.md, 5)."""
    if user.is_admin or (user.access_until and user.access_until > time.time()):
        return user
    raise AppError(402, "subscription_required", "Choose a plan to use BrewMyJob")


async def user_session(user: Annotated[CurrentUser, Depends(current_user)]) -> AsyncIterator[AsyncSession]:
    """A transaction scoped to the signed-in user. Commits on success, rolls back on error."""
    async with user_scope(user.id) as session:
        yield session


User = Annotated[CurrentUser, Depends(current_user)]
UserDB = Annotated[AsyncSession, Depends(user_session)]
