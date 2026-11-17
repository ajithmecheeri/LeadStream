"""Plans, access and invites (docs/plan-roles-and-plans.md). These routes stay open without a plan."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import CurrentUser, User, require_super_admin
from app.core.errors import NotFound
from app.modules.access import service
from app.modules.access.models import Invite
from app.modules.access.schemas import (
    AcceptIn,
    AccessOut,
    InviteIn,
    InviteMade,
    InviteOut,
    InviteView,
    PlanOut,
    PlansOut,
)
from app.modules.users.models import User as UserRow

router = APIRouter(tags=["access"])
DB = Annotated[AsyncSession, Depends(get_session)]
SuperAdmin = Annotated[CurrentUser, Depends(require_super_admin)]


access_out = service.access_out


@router.get("/plans", response_model=PlansOut)
async def plans(user: User, db: DB):
    """The plans and prices, and your access now. Paying comes later; an invite's coupon gives free months."""
    row = await db.get(UserRow, user.id)
    if row is None:
        raise NotFound("User")
    return PlansOut(
        plans=[
            PlanOut(id=p.id, months=p.months, price_inr=p.price_inr, label=p.label) for p in service.PLANS
        ],
        access=access_out(row),
        payments_open=False,
    )


# --- The invite's link -----------------------------------------------------------------------------------------


@router.get("/invites/view", response_model=InviteView)
async def view_invite(token: Annotated[str, Query(min_length=10, max_length=200)], db: DB):
    """What an invite link offers (no sign-in needed: the link is the secret)."""
    invite = await service.open_invite(db, token)
    has_account = await db.scalar(select(UserRow.id).where(UserRow.email == invite.email)) is not None
    return InviteView(
        email=invite.email, role=invite.role, free_months=invite.free_months, has_account=has_account
    )


@router.post("/invites/accept", response_model=AccessOut)
async def accept_invite(body: AcceptIn, user: User, db: DB):
    """Accept an invite with the account it was made for. Refresh the session afterwards for a new role."""
    invite = await service.open_invite(db, body.token)
    row = await db.get(UserRow, user.id)
    if row is None:
        raise NotFound("User")
    await service.accept(db, invite, row)
    return access_out(row)


# --- The super admin's invites -----------------------------------------------------------------------------------


def _out(i: Invite) -> InviteOut:
    return InviteOut(
        id=i.id,
        email=i.email,
        role=i.role,
        free_months=i.free_months,
        state=service.state(i),  # type: ignore[arg-type]
        created_at=i.created_at,
        expires_at=i.expires_at,
        accepted_at=i.accepted_at,
    )


@router.get("/admin/invites", response_model=list[InviteOut])
async def invites(_: SuperAdmin, db: DB):
    rows = await db.scalars(select(Invite).order_by(Invite.created_at.desc()).limit(200))
    return [_out(i) for i in rows]


@router.post("/admin/invites", response_model=InviteMade, status_code=status.HTTP_201_CREATED)
async def make_invite(body: InviteIn, admin: SuperAdmin, db: DB):
    """Invite a job seeker (optionally with a 1- or 3-month coupon) or an admin. No email is sent yet: copy the
    link and send it yourself."""
    invite, token = await service.create_invite(db, admin.id, str(body.email), body.role, body.free_months)
    await db.refresh(invite)
    return InviteMade(**_out(invite).model_dump(), link=service.link(token))


@router.delete("/admin/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(invite_id: UUID, _: SuperAdmin, db: DB):
    invite = await db.get(Invite, invite_id)
    if invite is None or service.state(invite) != "open":
        raise NotFound("Open invite")
    invite.revoked_at = datetime.now(UTC)
