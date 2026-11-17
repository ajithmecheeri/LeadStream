"""The browser extension's API (milestone 14.3).

Settings (signed in): make a pairing code, list and revoke paired browsers. The extension: trade the code for a
token, then read what application forms need (fill data, resume and cover letter files). The token can't change
anything, and nothing is served for a job-portal page.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.db import user_scope
from app.core.deps import User, UserDB
from app.core.errors import AppError, NotFound, Unauthorized
from app.modules.apply import service as apply
from app.modules.catalog.models import Job, JobSource
from app.modules.documents.models import CoverLetter, Resume, StoredFile
from app.modules.documents.router import _download
from app.modules.extension import service
from app.modules.extension.models import ExtensionToken
from app.modules.extension.schemas import (
    DeviceOut,
    FillData,
    FillJob,
    PairIn,
    PairingCodeOut,
    PairOut,
)
from app.modules.jobs.models import UserJob

router = APIRouter(prefix="/extension", tags=["extension"])


# --- Settings: pairing and paired browsers ----------------------------------------------------------------


@router.post("/pairing-code", response_model=PairingCodeOut, status_code=201)
async def pairing_code(user: User, db: UserDB):
    """A one-time code to paste into the BrewMyJob extension, valid for 10 minutes. A new code replaces an
    unused one."""
    await db.execute(
        ExtensionToken.__table__.delete().where(ExtensionToken.token_hash.is_(None))  # type: ignore[attr-defined]
    )
    code, digest = service.make(service.CODE_PREFIX, user.id)
    expires = datetime.now(UTC) + timedelta(minutes=service.CODE_MINUTES)
    db.add(ExtensionToken(user_id=user.id, pair_code_hash=digest, pair_expires_at=expires))
    return PairingCodeOut(code=code, expires_at=expires)


@router.get("/devices", response_model=list[DeviceOut])
async def devices(user: User, db: UserDB):
    """Browsers paired with your account, newest first."""
    rows = await db.scalars(
        select(ExtensionToken)
        .where(ExtensionToken.token_hash.is_not(None), ExtensionToken.revoked_at.is_(None))
        .order_by(ExtensionToken.paired_at.desc())
    )
    return list(rows)


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke(device_id: UUID, user: User, db: UserDB):
    """Unpair a browser: its token stops working at once."""
    row = await db.get(ExtensionToken, device_id)
    if row is None or row.token_hash is None or row.revoked_at is not None:
        raise NotFound("Paired browser")
    row.revoked_at = datetime.now(UTC)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- The extension ------------------------------------------------------------------------------------------


@router.post("/pair", response_model=PairOut)
async def pair(body: PairIn):
    """Trade a pairing code from Settings for this browser's token (shown once; keep it in the extension)."""
    parsed = service.parse(service.CODE_PREFIX, body.code)
    if parsed is None:
        raise AppError(400, "invalid_code", "That isn't a BrewMyJob pairing code")
    user_id, digest = parsed
    async with user_scope(user_id) as db:
        row = await db.scalar(
            select(ExtensionToken).where(ExtensionToken.pair_code_hash == digest).with_for_update()
        )
        if row is None or row.pair_expires_at is None or row.pair_expires_at < datetime.now(UTC):
            raise AppError(
                400, "invalid_code", "That code has expired or was used. Make a new one on Settings."
            )
        token, token_digest = service.make(service.TOKEN_PREFIX, user_id)
        row.token_hash, row.pair_code_hash, row.pair_expires_at = token_digest, None, None
        row.name, row.paired_at = body.name, datetime.now(UTC)
        facts = await apply.load(db, user_id)
        return PairOut(token=token, name=facts.user.name, email=facts.user.email)


@dataclass
class Paired:
    user_id: UUID
    db: AsyncSession


async def paired(request: Request) -> AsyncIterator[Paired]:
    """The extension's token from the Authorization header, checked in its user's scope."""
    header = request.headers.get("authorization", "")
    parsed = service.parse(service.TOKEN_PREFIX, header[7:]) if header.lower().startswith("bearer ") else None
    if parsed is None:
        raise Unauthorized("Pair the extension on Settings", code="invalid_token")
    user_id, digest = parsed
    async with user_scope(user_id) as db:
        row = await db.scalar(
            select(ExtensionToken).where(
                ExtensionToken.token_hash == digest, ExtensionToken.revoked_at.is_(None)
            )
        )
        if row is None:
            raise Unauthorized("This browser was unpaired. Pair it again on Settings.", code="invalid_token")
        await db.execute(
            update(ExtensionToken).where(ExtensionToken.id == row.id).values(last_used_at=datetime.now(UTC))
        )
        request.state.user_id = user_id
        yield Paired(user_id, db)


Extension = Annotated[Paired, Depends(paired)]


def _page(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


async def _job_for(db: AsyncSession, url: str) -> tuple[UserJob, Job] | None:
    """The user's job whose listing or apply link is this page, if any."""
    page = _page(url)
    if not page:
        return None
    variants = [page, page + "/"]
    row = (
        await db.execute(
            select(UserJob, Job)
            .join(Job, Job.id == UserJob.job_id)
            .outerjoin(JobSource, JobSource.job_id == Job.id)
            .where(or_(JobSource.url.in_(variants), UserJob.apply_url.in_(variants)))
            .order_by(UserJob.first_seen_at.desc())
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row else None


@router.get("/fill-data", response_model=FillData)
async def fill_data(ext: Extension, url: Annotated[str | None, Query(max_length=2000)] = None):
    """What the extension fills a company application form with. `url`: the form's page, to pick the job's
    suggested resume. Refused on job portals."""
    if service.blocked(url):
        raise AppError(403, "blocked_site", "BrewMyJob doesn't fill forms on job portals")
    db = ext.db
    f = await apply.load(db, ext.user_id)
    u, c, p = f.user, f.candidate, f.profile
    work = list(p.work_history) if p else []
    now = next((w for w in work if w.get("current")), work[0] if work else None)
    fields = {
        "first_name": u.first_name,
        "last_name": u.last_name,
        "full_name": u.name,
        "email": u.email,
        "phone": p and p.phone,
        "address_line1": p and p.address_line1,
        "address_line2": p and p.address_line2,
        "city": (p and p.city) or (c and c.current_location),
        "state": p and p.state,
        "postal_code": p and p.postal_code,
        "country": p and p.country,
        "linkedin": c and c.linkedin_url,
        "website": (p.websites[0] if p and p.websites else None),
        "current_title": now and now.get("title"),
        "current_company": now and now.get("company"),
        "years_experience": c and c.years_experience,
        "skills": ", ".join(f.skills) or None,
    }
    found = await _job_for(db, url) if url else None
    return FillData(
        fields={k: str(v) for k, v in fields.items() if v not in (None, "")},
        work_history=work,
        education=list(p.education) if p else [],
        languages=list(p.languages) if p else [],
        answers=[
            {"key": a.key.removeprefix("answer:"), "question": a.label, "answer": a.value}
            for a in apply.answers(f)
        ],
        documents=await apply.documents(db, found[0].id if found else None),
        job=FillJob(id=found[0].id, title=found[1].title, company=found[1].company) if found else None,
    )


async def _file(db: AsyncSession, file_id: UUID | None) -> Response:
    f = await db.get(StoredFile, file_id, options=[undefer(StoredFile.data)]) if file_id else None
    return _download(f)


@router.get("/resumes/{resume_id}/file", response_class=Response)
async def resume_file(resume_id: UUID, ext: Extension):
    """A resume's original file, to attach to the form."""
    row = await ext.db.get(Resume, resume_id)
    if row is None:
        raise NotFound("Resume")
    return await _file(ext.db, row.file_id)


@router.get("/cover-letters/{letter_id}/file", response_class=Response)
async def cover_letter_file(letter_id: UUID, ext: Extension):
    row = await ext.db.get(CoverLetter, letter_id)
    if row is None:
        raise NotFound("Cover letter")
    return await _file(ext.db, row.file_id)
