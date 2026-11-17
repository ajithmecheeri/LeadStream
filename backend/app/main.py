"""BrewMyJob API entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import dispose_engine, sessionmaker
from app.core.deps import require_access
from app.core.errors import install_error_handlers
from app.core.middleware import RequestContext
from app.core.worker import close as close_worker
from app.modules.access.router import router as access_router
from app.modules.admin.router import router as admin_router
from app.modules.alerts.router import router as alerts_router
from app.modules.applications.router import router as applications_router
from app.modules.auth.router import router as auth_router
from app.modules.candidate.router import router as candidate_router
from app.modules.documents.router import router as documents_router
from app.modules.feedback.router import router as feedback_router
from app.modules.ingestion.router import internal_router
from app.modules.ingestion.router import router as mail_router
from app.modules.jobs.router import router as jobs_router
from app.modules.matching.router import router as matching_router
from app.modules.notifications.router import router as notifications_router
from app.modules.profiles.router import router as profiles_router
from app.modules.readiness.router import router as readiness_router
from app.modules.settings.router import router as settings_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_worker()
    await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="BrewMyJob API",
        version="0.1.0",
        description="Job alerts in, fit scores and tailored packs out. You always submit.",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(RequestContext)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
    )
    install_error_handlers(app)

    v1 = APIRouter(prefix="/api/v1")
    # Open without a plan: signing up and in, the account, plans and invites, the
    # super admin's pages.
    for r in (
        auth_router,
        access_router,
        admin_router,
    ):
        v1.include_router(r)
    # Everything else needs a running plan or coupon for a job seeker (docs/plan-roles-and-plans.md, 5).
    for r in (
        candidate_router,
        profiles_router,
        settings_router,
        notifications_router,
        mail_router,
        jobs_router,
        documents_router,
        matching_router,
        readiness_router,
        applications_router,
        alerts_router,
        feedback_router,
    ):
        v1.include_router(r, dependencies=[Depends(require_access)])
    app.include_router(v1)
    app.include_router(internal_router)

    @app.get("/healthz", tags=["ops"])
    async def healthz():
        async with sessionmaker()() as db:
            await db.execute(text("select 1"))
        return {"status": "ok", "app": s.app_name, "env": s.env}

    return app


app = create_app()
