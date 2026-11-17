from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.deps import User as CurrentUserDep
from app.core.errors import AppError, NotFound, Unauthorized
from app.modules.access import service as access
from app.modules.auth import service
from app.modules.auth.schemas import LoginIn, MeOut, MePatch, RefreshIn, SignupIn, TokenOut
from app.modules.users.models import User

router = APIRouter(tags=["auth"])

COOKIE = "ff_refresh"
COOKIE_PATH = "/api/v1/auth"
DB = Annotated[AsyncSession, Depends(get_session)]
ClientHeader = Annotated[str | None, Header(alias="X-Client")]


def _client(x_client: str | None) -> str:
    return "mobile" if (x_client or "").lower() == "mobile" else "web"


def _set_cookie(response: Response, raw: str) -> None:
    s = get_settings()
    response.set_cookie(
        COOKIE,
        raw,
        max_age=s.refresh_token_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path=COOKIE_PATH,
    )


def _token_response(response: Response, client: str, user: User, access: str, ttl: int, raw: str) -> TokenOut:
    if client == "web":
        _set_cookie(response, raw)
    return TokenOut(
        access_token=access,
        expires_in=ttl,
        refresh_token=raw if client == "mobile" else None,
        user=service.me_out(user),
    )


def _meta(request: Request) -> tuple[str | None, str | None]:
    return request.headers.get("user-agent"), request.client.host if request.client else None


@router.post("/auth/signup", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupIn, request: Request, response: Response, db: DB, x_client: ClientHeader = None):
    """Create an account. Also creates an empty candidate profile, default notification settings and the consent record."""
    client = _client(x_client)
    invite = None
    if body.invite:
        invite = await access.open_invite(db, body.invite)
        if invite.email.lower() != str(body.email).lower():
            raise AppError(
                422,
                "validation_error",
                "Some fields need attention",
                [{"field": "email", "message": f"This invite is for {invite.email}"}],
            )
    user = await service.signup(db, body.email, body, body.password, body.whatsapp_number, body.job_locations)
    if invite is not None:
        await access.accept(db, invite, user)
    access_token, ttl, raw = await service.issue_tokens(db, user, client, *_meta(request))
    return _token_response(response, client, user, access_token, ttl, raw)


@router.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, response: Response, db: DB, x_client: ClientHeader = None):
    client = _client(x_client)
    user = await service.authenticate(db, body.email, body.password)
    access, ttl, raw = await service.issue_tokens(db, user, client, *_meta(request))
    return _token_response(response, client, user, access, ttl, raw)


@router.post("/auth/refresh", response_model=TokenOut)
async def refresh(
    request: Request, response: Response, db: DB, body: RefreshIn | None = None, x_client: ClientHeader = None
):
    """Rotate the refresh token (cookie for web, body for mobile) and return a new access token."""
    raw = (body.refresh_token if body else None) or request.cookies.get(COOKIE)
    if not raw:
        raise Unauthorized("Session expired, please sign in again", code="refresh_invalid")
    user, access, ttl, new_raw = await service.rotate(db, raw, *_meta(request))
    return _token_response(response, _client(x_client), user, access, ttl, new_raw)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: DB, body: RefreshIn | None = None):
    await service.logout(db, (body.refresh_token if body else None) or request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUserDep, db: DB):
    row = await db.get(User, user.id)
    if row is None:
        raise NotFound("User")
    return service.me_out(row)


@router.patch("/me", response_model=MeOut)
async def patch_me(body: MePatch, user: CurrentUserDep, db: DB):
    row = await db.get(User, user.id)
    if row is None:
        raise NotFound("User")
    parts = body.model_dump(exclude_unset=True, include={"first_name", "middle_name", "last_name"})
    if parts:
        clean = {k: " ".join((v or "").split()) or None for k, v in parts.items()}
        first = clean["first_name"] if "first_name" in clean else row.first_name
        last = clean["last_name"] if "last_name" in clean else row.last_name
        middle = clean["middle_name"] if "middle_name" in clean else row.middle_name
        missing = [f for f, v in (("first_name", first), ("last_name", last)) if not v]
        if missing:
            raise AppError(
                422,
                "validation_error",
                "Some fields need attention",
                [{"field": f, "message": "This name is required"} for f in missing],
            )
        service.set_name(row, first, middle, last)
    if body.timezone is not None:
        row.timezone = service.validate_timezone(body.timezone)
    await db.flush()
    await db.refresh(row)
    return service.me_out(row)
