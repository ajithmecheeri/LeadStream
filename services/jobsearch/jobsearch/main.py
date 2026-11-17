"""The Job Search Service's API app: `uvicorn jobsearch.main:app --port 8100`."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from jobsearch import errors
from jobsearch.api import router
from jobsearch.db import dispose_engine
from jobsearch.worker import close as close_queue

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_queue()
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="BrewMyJob Job Search Service", version="1", lifespan=lifespan, docs_url="/docs")
    errors.install(app)
    app.include_router(router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"ok": True}

    return app


app = create_app()
