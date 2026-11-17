"""Errors in the same envelope as the main app: {"error": {"code", "message", "details", "request_id"}}."""

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

log = logging.getLogger("jobsearch")


class AppError(Exception):
    status = 400

    def __init__(self, code: str, message: str, details: dict | None = None, status: int | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}
        if status:
            self.status = status


class NotFound(AppError):
    status = 404

    def __init__(self, what: str):
        super().__init__("not_found", f"{what} not found")


class Conflict(AppError):
    status = 409


def _body(request: Request, code: str, message: str, details: dict | None = None) -> dict:
    rid = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:16]
    return {"error": {"code": code, "message": message, "details": details or {}, "request_id": rid}}


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

    @app.exception_handler(AppError)
    async def app_error(request: Request, e: AppError):
        return JSONResponse(_body(request, e.code, e.message, e.details), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, e: RequestValidationError):
        fields = {".".join(str(p) for p in err["loc"][1:]): err["msg"] for err in e.errors()}
        return JSONResponse(
            _body(request, "validation_error", "Some fields are invalid", {"fields": fields}), status_code=422
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, e: HTTPException):
        code = {401: "unauthorized", 404: "not_found", 405: "method_not_allowed"}.get(e.status_code, "error")
        return JSONResponse(_body(request, code, str(e.detail)), status_code=e.status_code)

    @app.exception_handler(Exception)
    async def crash(request: Request, e: Exception):
        log.exception("unhandled error")
        return JSONResponse(_body(request, "internal_error", "Something went wrong"), status_code=500)
