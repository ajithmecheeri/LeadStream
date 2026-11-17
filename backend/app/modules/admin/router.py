"""Super admin: app settings. Becoming admin is a command-line step (`make admin EMAIL=…`), never an API call."""

from datetime import UTC, datetime
from typing import Annotated, Self

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.core.deps import CurrentUser, User, UserDB, require_super_admin
from app.modules.admin.models import AppSetting
from app.modules.admin.service import load
from app.modules.users.models import AuditEvent

router = APIRouter(tags=["admin"])
Admin = Annotated[CurrentUser, Depends(require_super_admin)]


class AppSettingsIO(BaseModel):
    job_expiry_warn_days: int = Field(
        ge=1, le=365, description="A job not seen in an alert for this many days shows 'May have expired'"
    )
    job_expiry_auto_days: int = Field(
        ge=1, le=365, description="After this many days it moves to Expired by itself (never an applied job)"
    )

    @model_validator(mode="after")
    def _order(self) -> Self:
        if self.job_expiry_auto_days < self.job_expiry_warn_days:
            raise ValueError("Moving to Expired can't come before the warning: use at least as many days")
        return self


class AdminSettingsOut(AppSettingsIO):
    updated_at: datetime | None


@router.get("/app-settings", response_model=AppSettingsIO)
async def app_settings(_: User, db: UserDB):
    """The values the super admin set, for every signed-in user."""
    return AppSettingsIO(**(await load(db)).__dict__)


async def _admin_view(db) -> AdminSettingsOut:
    last = await db.scalar(select(AppSetting.updated_at).order_by(AppSetting.updated_at.desc()).limit(1))
    return AdminSettingsOut(**(await load(db)).__dict__, updated_at=last)


@router.get("/admin/settings", response_model=AdminSettingsOut)
async def admin_settings(_: Admin, db: UserDB):
    return await _admin_view(db)


@router.put("/admin/settings", response_model=AdminSettingsOut)
async def put_admin_settings(body: AppSettingsIO, admin: Admin, db: UserDB):
    rows = {s.key: s for s in await db.scalars(select(AppSetting).with_for_update())}
    changed = {}
    for key, value in body.model_dump().items():
        row = rows.get(key)
        if row is None or row.value == value:
            continue
        changed[key] = {"from": row.value, "to": value}
        row.value, row.updated_by, row.updated_at = value, admin.id, datetime.now(UTC)
    if changed:
        db.add(AuditEvent(user_id=admin.id, actor="admin", event="app_settings_changed", meta=changed))
    await db.flush()
    return await _admin_view(db)
