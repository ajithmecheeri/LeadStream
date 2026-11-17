"""App settings: values the super admin changes without a redeploy (docs/plan-m5.md)."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.admin.models import AppSetting

DEFAULTS = {"job_expiry_warn_days": 30, "job_expiry_auto_days": 45}


@dataclass(frozen=True)
class AppValues:
    job_expiry_warn_days: int
    job_expiry_auto_days: int


async def load(db: AsyncSession) -> AppValues:
    """Current values; a key missing from the table falls back to its default."""
    stored = {s.key: s.value for s in await db.scalars(select(AppSetting))}
    return AppValues(**{k: int(stored.get(k, d)) for k, d in DEFAULTS.items()})
