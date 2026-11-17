"""The resume and cover-letter library: one primary resume and up to three variations, up to five cover
letters with one default. Every change queues a re-score of the user's jobs."""

import base64
import binascii
import hashlib
import re
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.config import get_settings
from app.core.deps import User, UserDB
from app.core.errors import AppError, Conflict, NotFound
from app.modules.documents.extract import UnreadableDocument, kind_of, text_of
from app.modules.documents.models import CoverLetter, Resume, StoredFile
from app.modules.documents.schemas import (
    MAX_COVER_LETTERS,
    MAX_RESUMES,
    CoverLetterDetail,
    CoverLetterList,
    CoverLetterOut,
    CoverLetterPatch,
    DocumentIn,
    ResumeDetail,
    ResumeIn,
    ResumeList,
    ResumeOut,
    ResumePatch,
)
from app.modules.matching.service import queue_scoring
from app.modules.profiles.models import SearchProfile
from app.modules.profiles.service import ensure_match_profiles

router = APIRouter(tags=["documents"])

MEDIA_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "odt": "application/vnd.oasis.opendocument.text",
    "rtf": "application/rtf",
    "txt": "text/plain; charset=utf-8",
    "md": "text/markdown; charset=utf-8",
}


def _default_label(body: DocumentIn, fallback: str) -> str:
    if body.label:
        return body.label
    if body.file_name:
        stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", body.file_name.rsplit("/", 1)[-1])
        stem = " ".join(stem.replace("_", " ").replace("-", " ").split())
        if stem:
            return stem[:60]
    return fallback


async def _read_upload(db: AsyncSession, user_id: UUID, body: DocumentIn) -> tuple[str, StoredFile | None]:
    """The document's text, and the stored original when it was a file. Raises 422 when unreadable."""
    try:
        if body.text:
            return text_of("txt", body.text.encode()), None
        try:
            data = base64.b64decode(body.content_base64 or "", validate=True)
        except (binascii.Error, ValueError) as e:
            raise AppError(422, "unreadable", "The file couldn't be decoded") from e
        if len(data) > get_settings().document_max_bytes:
            raise AppError(422, "too_large", "Files up to 5 MB are accepted")
        kind = kind_of(body.file_name or "", data)
        text = text_of(kind, data)
    except UnreadableDocument as e:
        raise AppError(422, "unreadable", str(e)) from e
    f = StoredFile(
        user_id=user_id,
        name=body.file_name or "document",
        kind=kind,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data=data,
    )
    db.add(f)
    await db.flush()
    return text, f


async def _files(db: AsyncSession, ids: list[UUID | None]) -> dict[UUID, StoredFile]:
    wanted = [i for i in ids if i]
    if not wanted:
        return {}
    return {f.id: f for f in await db.scalars(select(StoredFile).where(StoredFile.id.in_(wanted)))}


def _file_info(f: StoredFile | None, text: str) -> dict:
    return {
        "file_name": f.name if f else None,
        "file_kind": f.kind if f else None,
        "file_size": f.size if f else None,
        "characters": len(text),
    }


def _resume_out(r: Resume, f: StoredFile | None, detail: bool = False) -> ResumeOut:
    data = {
        "id": r.id,
        "label": r.label,
        "focus_tags": r.focus_tags,
        "search_profile_id": r.search_profile_id,
        "is_primary": r.is_primary,
        "source": r.source,
        "version": r.version,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
        **_file_info(f, r.text),
    }
    return ResumeDetail(**data, text=r.text) if detail else ResumeOut(**data)


def _letter_out(c: CoverLetter, f: StoredFile | None, detail: bool = False) -> CoverLetterOut:
    data = {
        "id": c.id,
        "label": c.label,
        "is_default": c.is_default,
        "version": c.version,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
        **_file_info(f, c.text),
    }
    return CoverLetterDetail(**data, text=c.text) if detail else CoverLetterOut(**data)


def _download(f: StoredFile | None) -> Response:
    if f is None:
        raise NotFound("File (this one was pasted as text)")
    return Response(
        content=f.data,
        media_type=MEDIA_TYPES.get(f.kind, "application/octet-stream"),
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(f.name)}"},
    )


# --- Resumes ----------------------------------------------------------------------------------------------


async def _resumes(db: AsyncSession) -> list[Resume]:
    return list(await db.scalars(select(Resume).order_by(Resume.is_primary.desc(), Resume.created_at)))


async def _resume_list(db: AsyncSession) -> ResumeList:
    rows = await _resumes(db)
    files = await _files(db, [r.file_id for r in rows])
    return ResumeList(items=[_resume_out(r, files.get(r.file_id)) for r in rows])


async def _get_resume(db: AsyncSession, resume_id: UUID, lock: bool = False) -> Resume:
    row = await db.get(Resume, resume_id, with_for_update=lock)
    if row is None:
        raise NotFound("Resume")
    return row


@router.get("/resumes", response_model=ResumeList)
async def list_resumes(_: User, db: UserDB):
    return await _resume_list(db)


@router.post("/resumes", response_model=ResumeDetail, status_code=status.HTTP_201_CREATED)
async def add_resume(body: ResumeIn, user: User, db: UserDB):
    """Upload a resume (PDF, Word, OpenDocument, RTF or text) or paste its text. The first one is primary."""
    count = await db.scalar(select(func.count()).select_from(Resume)) or 0
    if count >= MAX_RESUMES:
        raise AppError(
            422,
            "limit_reached",
            f"You can keep one primary resume and up to {MAX_RESUMES - 1} variations. Delete one first.",
        )
    text, f = await _read_upload(db, user.id, body)
    if await db.scalar(select(Resume.id).where(Resume.text == text)):
        raise Conflict("duplicate", "This resume is already in your library")
    row = Resume(
        user_id=user.id,
        label=_default_label(body, f"Resume {count + 1}"),
        focus_tags=[t.strip() for t in body.focus_tags if t.strip()],
        text=text,
        file_id=f.id if f else None,
        source="upload" if f else "paste",
        is_primary=count == 0,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    await ensure_match_profiles(db, user.id)  # its Skill Match profile, made from it (2026-11-13)
    await queue_scoring(user.id, "resume added")
    return _resume_out(row, f, detail=True)


@router.post("/resumes/{resume_id}/replace", response_model=ResumeDetail)
async def replace_resume(resume_id: UUID, body: DocumentIn, user: User, db: UserDB):
    """Upload a new version of a resume (after adding a skill to it, say). It keeps its label, primary flag and
    match profile; the profile's skills are read again from the new version, the skills you added stay."""
    row = await _get_resume(db, resume_id, lock=True)
    text, f = await _read_upload(db, user.id, body)
    if await db.scalar(select(Resume.id).where(Resume.text == text, Resume.id != row.id)):
        raise Conflict("duplicate", "This resume is already in your library")
    old_file = row.file_id
    row.text, row.file_id, row.source = text, f.id if f else None, "upload" if f else "paste"
    row.embedding, row.embedding_key = None, None
    row.version += 1
    await db.flush()
    if old_file and old_file != row.file_id:
        await db.execute(StoredFile.__table__.delete().where(StoredFile.id == old_file))
    await db.refresh(row)
    await ensure_match_profiles(db, user.id)
    await queue_scoring(user.id, "resume replaced")
    return _resume_out(row, f, detail=True)


@router.get("/resumes/{resume_id}", response_model=ResumeDetail)
async def get_resume(resume_id: UUID, _: User, db: UserDB):
    row = await _get_resume(db, resume_id)
    return _resume_out(row, (await _files(db, [row.file_id])).get(row.file_id), detail=True)


@router.patch("/resumes/{resume_id}", response_model=ResumeDetail)
async def patch_resume(resume_id: UUID, body: ResumePatch, user: User, db: UserDB):
    row = await _get_resume(db, resume_id, lock=True)
    if body.version != row.version:
        raise Conflict("version_conflict", "This resume was changed elsewhere. Reload and try again.")
    if body.label is not None:
        row.label = " ".join(body.label.split())
    if body.focus_tags is not None:
        row.focus_tags = [t.strip() for t in body.focus_tags if t.strip()]
    if "search_profile_id" in body.model_fields_set:
        if body.search_profile_id and await db.get(SearchProfile, body.search_profile_id) is None:
            raise AppError(422, "validation_error", "That search profile doesn't exist")
        row.search_profile_id = body.search_profile_id
    row.version += 1
    await db.flush()
    await db.refresh(row)
    return _resume_out(row, (await _files(db, [row.file_id])).get(row.file_id), detail=True)


@router.post("/resumes/{resume_id}/primary", response_model=ResumeList)
async def make_primary(resume_id: UUID, user: User, db: UserDB):
    row = await _get_resume(db, resume_id, lock=True)
    if not row.is_primary:
        for other in await _resumes(db):
            if other.is_primary:
                other.is_primary = False
                other.version += 1
        await db.flush()  # one primary at a time (unique index)
        row.is_primary = True
        row.version += 1
        await db.flush()
        await queue_scoring(user.id, "primary resume changed")
    return await _resume_list(db)


@router.delete("/resumes/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(resume_id: UUID, user: User, db: UserDB):
    """Delete a resume and its Skill Match profile (with the skills you added there)."""
    row = await _get_resume(db, resume_id, lock=True)
    was_primary, file_id = row.is_primary, row.file_id
    await db.execute(delete(SearchProfile).where(SearchProfile.resume_id == row.id))
    await db.delete(row)
    if file_id:
        await db.execute(StoredFile.__table__.delete().where(StoredFile.id == file_id))
    await db.flush()
    if was_primary:
        rest = await _resumes(db)
        if rest:
            rest[0].is_primary = True
            rest[0].version += 1
    await queue_scoring(user.id, "resume deleted")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/resumes/{resume_id}/file", response_class=Response)
async def resume_file(resume_id: UUID, _: User, db: UserDB):
    """The original upload, exactly as it was sent."""
    row = await _get_resume(db, resume_id)
    if row.file_id is None:
        return _download(None)
    f = await db.get(StoredFile, row.file_id, options=[undefer(StoredFile.data)])
    return _download(f)


# --- Cover letters ----------------------------------------------------------------------------------------


async def _letters(db: AsyncSession) -> list[CoverLetter]:
    return list(
        await db.scalars(select(CoverLetter).order_by(CoverLetter.is_default.desc(), CoverLetter.created_at))
    )


async def _letter_list(db: AsyncSession) -> CoverLetterList:
    rows = await _letters(db)
    files = await _files(db, [c.file_id for c in rows])
    return CoverLetterList(items=[_letter_out(c, files.get(c.file_id)) for c in rows])


async def _get_letter(db: AsyncSession, letter_id: UUID, lock: bool = False) -> CoverLetter:
    row = await db.get(CoverLetter, letter_id, with_for_update=lock)
    if row is None:
        raise NotFound("Cover letter")
    return row


@router.get("/cover-letters", response_model=CoverLetterList)
async def list_letters(_: User, db: UserDB):
    return await _letter_list(db)


@router.post("/cover-letters", response_model=CoverLetterDetail, status_code=status.HTTP_201_CREATED)
async def add_letter(body: DocumentIn, user: User, db: UserDB):
    """Upload a cover letter or write one in the app. The first one is the default."""
    count = await db.scalar(select(func.count()).select_from(CoverLetter)) or 0
    if count >= MAX_COVER_LETTERS:
        raise AppError(
            422, "limit_reached", f"You can keep up to {MAX_COVER_LETTERS} cover letters. Delete one first."
        )
    text, f = await _read_upload(db, user.id, body)
    if await db.scalar(select(CoverLetter.id).where(CoverLetter.text == text)):
        raise Conflict("duplicate", "This cover letter is already in your library")
    row = CoverLetter(
        user_id=user.id,
        label=_default_label(body, f"Cover letter {count + 1}"),
        text=text,
        file_id=f.id if f else None,
        is_default=count == 0,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    await queue_scoring(user.id, "cover letter added")
    return _letter_out(row, f, detail=True)


@router.get("/cover-letters/{letter_id}", response_model=CoverLetterDetail)
async def get_letter(letter_id: UUID, _: User, db: UserDB):
    row = await _get_letter(db, letter_id)
    return _letter_out(row, (await _files(db, [row.file_id])).get(row.file_id), detail=True)


@router.patch("/cover-letters/{letter_id}", response_model=CoverLetterDetail)
async def patch_letter(letter_id: UUID, body: CoverLetterPatch, user: User, db: UserDB):
    row = await _get_letter(db, letter_id, lock=True)
    if body.version != row.version:
        raise Conflict("version_conflict", "This cover letter was changed elsewhere. Reload and try again.")
    if body.label is not None:
        row.label = " ".join(body.label.split())
    if body.text is not None and body.text.strip() != row.text:
        row.text = body.text.strip()
        await queue_scoring(user.id, "cover letter edited")
    row.version += 1
    await db.flush()
    await db.refresh(row)
    return _letter_out(row, (await _files(db, [row.file_id])).get(row.file_id), detail=True)


@router.post("/cover-letters/{letter_id}/default", response_model=CoverLetterList)
async def make_default(letter_id: UUID, user: User, db: UserDB):
    row = await _get_letter(db, letter_id, lock=True)
    if not row.is_default:
        for other in await _letters(db):
            if other.is_default:
                other.is_default = False
                other.version += 1
        await db.flush()
        row.is_default = True
        row.version += 1
        await db.flush()
        await queue_scoring(user.id, "default cover letter changed")
    return await _letter_list(db)


@router.delete("/cover-letters/{letter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_letter(letter_id: UUID, user: User, db: UserDB):
    row = await _get_letter(db, letter_id, lock=True)
    was_default, file_id = row.is_default, row.file_id
    await db.delete(row)
    if file_id:
        await db.execute(StoredFile.__table__.delete().where(StoredFile.id == file_id))
    await db.flush()
    if was_default:
        rest = await _letters(db)
        if rest:
            rest[0].is_default = True
            rest[0].version += 1
    await queue_scoring(user.id, "cover letter deleted")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/cover-letters/{letter_id}/file", response_class=Response)
async def letter_file(letter_id: UUID, _: User, db: UserDB):
    row = await _get_letter(db, letter_id)
    if row.file_id is None:
        return _download(None)
    f = await db.get(StoredFile, row.file_id, options=[undefer(StoredFile.data)])
    return _download(f)
