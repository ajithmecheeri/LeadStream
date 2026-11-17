"""The service's background jobs (Procrastinate, with its queue in the service's own database).

Schedules (docs/jobsearch-plan-discovery.md, section 11), in UTC:
  - every 3 hours, on the hour: each employer board is queued once (its own task, so one slow or failing board
    never holds up the others);
  - every 6 hours, at :30: the job APIs (Adzuna) for each search area, within the daily quota.
Run it with `make dev-jobsearch-worker` or the `jobsearch-worker` container.
"""

import logging
from uuid import UUID

import procrastinate
from procrastinate.exceptions import AlreadyEnqueued

from jobsearch.config import get_settings

log = logging.getLogger("jobsearch")

BOARDS_CRON = "0 */3 * * *"
APIS_CRON = "30 */6 * * *"
CHECK_BOARD = "jobsearch.check_board"


def _conninfo(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(conninfo=_conninfo(get_settings().database_url)),
    import_paths=["jobsearch.worker"],
)

_open = False


async def defer(task_name: str, *, queueing_lock: str | None = None, **kwargs) -> int:
    global _open
    if not _open:
        await app.open_async()
        _open = True
    return await app.configure_task(task_name, queueing_lock=queueing_lock).defer_async(**kwargs)


async def close() -> None:
    global _open
    if _open:
        await app.close_async()
        _open = False


async def queue_board(board_id: UUID) -> None:
    try:
        await defer(CHECK_BOARD, queueing_lock=f"board:{board_id}", board_id=str(board_id))
    except AlreadyEnqueued:
        pass


@app.task(name=CHECK_BOARD, queue="boards", retry=procrastinate.RetryStrategy(max_attempts=2, wait=120))
async def check_board_task(board_id: str) -> None:
    from jobsearch.service import check_board

    try:
        await check_board(UUID(board_id))
    except LookupError:
        log.warning("board %s was removed before its check", board_id)


@app.periodic(cron=BOARDS_CRON, periodic_id="boards")
@app.task(name="jobsearch.boards", queue="boards", queueing_lock="jobsearch.boards")
async def boards(timestamp: int) -> None:
    from jobsearch.service import due_boards

    ids = await due_boards()
    for board_id in ids:
        try:
            await app.configure_task(CHECK_BOARD, queueing_lock=f"board:{board_id}").defer_async(
                board_id=str(board_id)
            )
        except AlreadyEnqueued:
            pass
    log.info("queued %d boards", len(ids))


@app.periodic(cron=APIS_CRON, periodic_id="apis")
@app.task(name="jobsearch.apis", queue="apis", queueing_lock="jobsearch.apis")
async def apis(timestamp: int) -> None:
    from jobsearch.service import run_apis

    runs = await run_apis()
    log.info("job APIs: %d search areas", len(runs))
