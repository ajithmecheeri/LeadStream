"""Background jobs: Procrastinate, a task queue that lives in Postgres (no extra service).

The worker connects as the app role, like the API, so row-level security applies to every task: a task
that touches private tables takes the user's id as an argument and works inside `user_scope(user_id)`.

Run it with `make dev-worker` (or the `worker` container). Each module with tasks is listed in
TASK_MODULES so the worker can find them. The API queues work by task name with `defer`.
"""

import procrastinate

from app.core.config import get_settings

TASK_MODULES = [
    "app.modules.ingestion.tasks",
    "app.modules.matching.tasks",
    "app.modules.jobs.tasks",
    "app.modules.alerts.tasks",
    "app.modules.notifications.tasks",
]


def _conninfo(url: str) -> str:
    # The app uses SQLAlchemy URLs (postgresql+asyncpg://…); psycopg wants a plain libpq URL.
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=_conninfo(get_settings().database_url)),
    import_paths=TASK_MODULES,
)

_open = False


async def defer(
    task_name: str, *, queueing_lock: str | None = None, schedule_in_seconds: int | None = None, **kwargs
) -> int:
    """Queue a task by name from the API. The connection pool opens on first use.

    `queueing_lock`: while a job with this lock is waiting, another defer raises AlreadyEnqueued.
    `schedule_in_seconds`: run it later (lets the caller's transaction commit first).
    """
    global _open
    if not _open:
        await app.open_async()
        _open = True
    options: dict = {"queueing_lock": queueing_lock}
    if schedule_in_seconds:
        options["schedule_in"] = {"seconds": schedule_in_seconds}
    return await app.configure_task(name=task_name, **options).defer_async(**kwargs)


async def close() -> None:
    global _open
    if _open:
        await app.close_async()
        _open = False
