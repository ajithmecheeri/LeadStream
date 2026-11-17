from datetime import time

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.core.deps import User, UserDB
from app.core.errors import NotFound
from app.modules.settings.models import NotificationSettings

router = APIRouter(tags=["settings"])


class NotificationSettingsIO(BaseModel):
    model_config = {"from_attributes": True}
    push: bool = True
    email: bool = True
    quiet_start: time | None = None
    quiet_end: time | None = None
    max_push_per_day: int = Field(10, ge=0, le=50)
    digest_time: time = time(19, 0)
    network_daily_cap: int = Field(5, ge=0, le=20)
    network_weekly_limit: int = Field(
        100, ge=0, le=200, description="LinkedIn's own weekly invitation limit is roughly 100"
    )


@router.get("/settings/notifications", response_model=NotificationSettingsIO)
async def get_notifications(user: User, db: UserDB):
    row = await db.get(NotificationSettings, user.id)
    if row is None:
        raise NotFound("Notification settings")
    return row


@router.put("/settings/notifications", response_model=NotificationSettingsIO)
async def put_notifications(body: NotificationSettingsIO, user: User, db: UserDB):
    row = await db.get(NotificationSettings, user.id)
    if row is None:
        raise NotFound("Notification settings")
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    await db.flush()
    return row
