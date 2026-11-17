"""Worker task: once a day, move jobs past the super admin's number of days to Expired."""

import logging

from sqlalchemy import select

from app.core.db import sessionmaker
from app.core.worker import app
from app.modules.admin.service import load
from app.modules.jobs.expiry import expire_old_jobs
from app.modules.users.models import User

log = logging.getLogger("fitfirst.jobs")

EXPIRE = "jobs.expire_old"


@app.periodic(cron="30 2 * * *", periodic_id="expire")  # 02:30 in the worker's time zone (UTC in Docker)
@app.task(name=EXPIRE, queue="ingest", queueing_lock=EXPIRE)
async def expire_old(timestamp: int) -> None:
    # users and app_settings have no RLS; each user's jobs are updated inside user_scope.
    async with sessionmaker()() as db:
        days = (await load(db)).job_expiry_auto_days
        user_ids = list(await db.scalars(select(User.id).order_by(User.created_at)))
    moved = 0
    for uid in user_ids:
        moved += await expire_old_jobs(uid, days)
    if moved:
        log.info("moved %d jobs to Expired (no sign of life for %d days)", moved, days)
